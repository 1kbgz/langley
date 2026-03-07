"""Langley WebSocket endpoint — multiplexed real-time subscriptions.

Protocol (JSON frames):

Client → Server:
    {"type": "subscribe", "channel": "<channel_name>"}
    {"type": "unsubscribe", "channel": "<channel_name>"}
    {"type": "send", "channel": "<channel_name>", "body": {...}, "headers": {...}}
    {"type": "ping"}

Server → Client:
    {"type": "message", "channel": "<channel_name>", "data": {...}}
    {"type": "subscribed", "channel": "<channel_name>"}
    {"type": "unsubscribed", "channel": "<channel_name>"}
    {"type": "sent", "message_id": "...", "sequence": N}
    {"type": "pong"}
    {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
import threading
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from langley.models import Message
from langley.server_state import ServerState
from langley.transport import Subscription

logger = logging.getLogger(__name__)


class WebSocketSession:
    """Manages subscriptions for a single WebSocket connection."""

    def __init__(self, ws: WebSocket, state: ServerState):
        self.ws = ws
        self.state = state
        self._subscriptions: dict[str, Subscription] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._closed = False

    async def run(self) -> None:
        """Accept the WebSocket and process frames until disconnect."""
        await self.ws.accept()
        try:
            while True:
                raw = await self.ws.receive_text()
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_error("Invalid JSON")
                    continue
                await self._handle_frame(frame)
        except WebSocketDisconnect:
            pass
        finally:
            self._closed = True
            await self._cleanup()

    async def _handle_frame(self, frame: dict[str, Any]) -> None:
        frame_type = frame.get("type", "")
        if frame_type == "ping":
            await self._send({"type": "pong"})
        elif frame_type == "subscribe":
            await self._handle_subscribe(frame)
        elif frame_type == "unsubscribe":
            await self._handle_unsubscribe(frame)
        elif frame_type == "send":
            await self._handle_send(frame)
        else:
            await self._send_error(f"Unknown frame type: {frame_type}")

    async def _handle_subscribe(self, frame: dict[str, Any]) -> None:
        channel = frame.get("channel", "")
        if not channel:
            await self._send_error("channel is required for subscribe")
            return
        if channel in self._subscriptions:
            await self._send({"type": "subscribed", "channel": channel})
            return

        # Subscribe on the transport; messages come in via a callback on a
        # background thread, so we need to schedule sends on the event loop.
        loop = asyncio.get_running_loop()

        def _on_message(msg: Message) -> None:
            if self._closed:
                return
            asyncio.run_coroutine_threadsafe(
                self._send({"type": "message", "channel": channel, "data": msg.to_dict()}),
                loop,
            )

        sub = self.state.transport.subscribe(channel, _on_message)
        self._subscriptions[channel] = sub
        await self._send({"type": "subscribed", "channel": channel})

    async def _handle_unsubscribe(self, frame: dict[str, Any]) -> None:
        channel = frame.get("channel", "")
        if not channel:
            await self._send_error("channel is required for unsubscribe")
            return
        sub = self._subscriptions.pop(channel, None)
        if sub is not None:
            sub.unsubscribe()
        await self._send({"type": "unsubscribed", "channel": channel})

    async def _handle_send(self, frame: dict[str, Any]) -> None:
        channel = frame.get("channel", "")
        if not channel:
            await self._send_error("channel is required for send")
            return
        body = frame.get("body", {})
        headers = frame.get("headers", {})
        msg = Message(
            channel=channel,
            body=body,
            sender="ws",
            headers=headers,
        )
        receipt = self.state.transport.send(channel, msg)
        await self._send({
            "type": "sent",
            "message_id": receipt.message_id,
            "sequence": receipt.sequence,
        })

    async def _send(self, data: dict[str, Any]) -> None:
        if not self._closed:
            try:
                await self.ws.send_json(data)
            except Exception:
                self._closed = True

    async def _send_error(self, message: str) -> None:
        await self._send({"type": "error", "message": message})

    async def _cleanup(self) -> None:
        for sub in self._subscriptions.values():
            sub.unsubscribe()
        self._subscriptions.clear()


async def websocket_endpoint(ws: WebSocket) -> None:
    """Starlette WebSocket route handler."""
    state: ServerState = ws.app.state.server
    session = WebSocketSession(ws, state)
    await session.run()
