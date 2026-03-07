"""Agent SDK — lightweight API for agents to integrate with langley.

An agent process imports this module and uses it to communicate with the
langley control plane: send/receive messages, checkpoint state, emit audit
events, report status, and request human approvals.

Configuration is read from environment variables set by the process manager:
    LANGLEY_AGENT_ID, LANGLEY_TENANT_ID, LANGLEY_PROFILE_ID, LANGLEY_PROFILE_NAME,
    LANGLEY_TRANSPORT_DIR (base path for FileMessageTransport).
"""

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from langley.models import CheckpointData, Message, _new_id, _now
from langley.transport import FileMessageTransport, MessageTransport, Subscription

logger = logging.getLogger(__name__)


@dataclass
class AgentContext:
    """Context available to a running agent."""

    agent_id: str
    tenant_id: str
    profile_id: str
    profile_name: str
    checkpoint: CheckpointData | None = None


class AgentSDK:
    """SDK used by agent code to communicate with the langley platform.

    Usage:
        sdk = AgentSDK.from_env()   # reads LANGLEY_* env vars
        sdk.send("output", {"result": 42})
        for msg in sdk.receive("input"):
            process(msg)
    """

    def __init__(
        self,
        context: AgentContext,
        transport: MessageTransport,
    ):
        self._context = context
        self._transport = transport
        self._subscriptions: list[Subscription] = []
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    @classmethod
    def from_env(cls, transport_dir: str | None = None) -> "AgentSDK":
        """Create an AgentSDK from environment variables.

        The process manager sets these when launching the agent subprocess.
        """
        agent_id = os.environ.get("LANGLEY_AGENT_ID", "")
        tenant_id = os.environ.get("LANGLEY_TENANT_ID", "")
        profile_id = os.environ.get("LANGLEY_PROFILE_ID", "")
        profile_name = os.environ.get("LANGLEY_PROFILE_NAME", "")

        if not agent_id:
            raise RuntimeError("LANGLEY_AGENT_ID environment variable is not set")

        ctx = AgentContext(
            agent_id=agent_id,
            tenant_id=tenant_id,
            profile_id=profile_id,
            profile_name=profile_name,
        )

        if transport_dir is None:
            transport_dir = os.environ.get("LANGLEY_TRANSPORT_DIR", "/tmp/langley/transport")

        transport = FileMessageTransport(transport_dir)

        return cls(context=ctx, transport=transport)

    @property
    def context(self) -> AgentContext:
        """Return the agent's context."""
        return self._context

    @property
    def agent_id(self) -> str:
        return self._context.agent_id

    @property
    def tenant_id(self) -> str:
        return self._context.tenant_id

    def send(self, channel: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        """Send a message on a channel."""
        msg = Message(
            channel=channel,
            body=body,
            sender=self._context.agent_id,
            headers=headers or {},
        )
        self._transport.send(channel, msg)

    def send_to(self, recipient: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        """Send a direct message to another agent via their inbox channel."""
        channel = f"agent.{recipient}.inbox"
        msg = Message(
            channel=channel,
            body=body,
            sender=self._context.agent_id,
            recipient=recipient,
            headers=headers or {},
        )
        self._transport.send(channel, msg)

    def subscribe(self, channel: str, handler: Callable[[Message], None]) -> Subscription:
        """Subscribe to messages on a channel."""
        sub = self._transport.subscribe(channel, handler)
        self._subscriptions.append(sub)
        return sub

    def receive(self, channel: str | None = None, from_seq: int = 0) -> Iterator[Message]:
        """Replay messages from a channel. Defaults to this agent's inbox."""
        if channel is None:
            channel = f"agent.{self._context.agent_id}.inbox"
        return self._transport.replay(channel, from_seq=from_seq)

    def report_status(self, status: dict[str, Any]) -> None:
        """Publish a status update visible in the UI."""
        self.send(
            f"agent.{self._context.agent_id}.status",
            {
                "type": "status_update",
                "agent_id": self._context.agent_id,
                "status": status,
                "timestamp": _now(),
            },
        )

    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """Emit a structured log entry that feeds into the audit trail."""
        self.send(
            f"agent.{self._context.agent_id}.logs",
            {
                "type": "log",
                "level": level,
                "message": message,
                "agent_id": self._context.agent_id,
                "timestamp": _now(),
                **kwargs,
            },
        )

    def request_approval(self, description: str, metadata: dict[str, Any] | None = None) -> str:
        """Submit an approval request. Returns the request ID.

        The actual waiting/polling for approval should be done by the
        caller checking the approval response channel.
        """
        request_id = _new_id()
        self.send(
            f"agent.{self._context.agent_id}.approvals",
            {
                "type": "approval_request",
                "request_id": request_id,
                "agent_id": self._context.agent_id,
                "description": description,
                "metadata": metadata or {},
                "timestamp": _now(),
            },
        )
        return request_id

    def emit_heartbeat(self) -> None:
        """Send a single heartbeat message."""
        self.send(
            "agent.heartbeats",
            {
                "type": "heartbeat",
                "agent_id": self._context.agent_id,
                "tenant_id": self._context.tenant_id,
                "timestamp": _now(),
            },
        )

    def start_heartbeat(self, interval: float = 5.0) -> None:
        """Start a background thread that emits heartbeats at a fixed interval."""
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_stop.clear()

        def _loop():
            while not self._heartbeat_stop.is_set():
                try:
                    self.emit_heartbeat()
                except Exception:
                    logger.exception("Failed to emit heartbeat")
                self._heartbeat_stop.wait(interval)

        self._heartbeat_thread = threading.Thread(target=_loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        """Stop the background heartbeat thread."""
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    def close(self) -> None:
        """Clean up all subscriptions and resources."""
        self.stop_heartbeat()
        for sub in self._subscriptions:
            sub.unsubscribe()
        self._subscriptions.clear()
        self._transport.close()
