"""GitHub Copilot provider — wraps the optional ``copilot-sdk`` package."""

from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Any

from langley.providers.base import LLMProvider

logger = logging.getLogger(__name__)

_DEFAULT_COPILOT_CLI = os.environ.get(
    "LANGLEY_COPILOT_CLI_PATH",
    os.path.expanduser("~/.config/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot"),
)


def _find_copilot_cli() -> str:
    """Locate the copilot CLI binary."""
    explicit = os.environ.get("LANGLEY_COPILOT_CLI_PATH")
    if explicit and os.path.isfile(explicit):
        return explicit
    if os.path.isfile(_DEFAULT_COPILOT_CLI):
        return _DEFAULT_COPILOT_CLI
    on_path = shutil.which("copilot")
    if on_path:
        return on_path
    raise RuntimeError("copilot CLI not found. Install GitHub Copilot in VS Code, or set LANGLEY_COPILOT_CLI_PATH.")


class CopilotProvider(LLMProvider):
    """Bridges a Copilot SDK session with the agent runner."""

    async def start(self) -> None:
        from copilot import CopilotClient, PermissionHandler  # optional external dep

        self._client: Any = CopilotClient({"cli_path": _find_copilot_cli()})
        await self._client.start()

        session_config: dict[str, Any] = {
            "on_permission_request": PermissionHandler.approve_all,
            "streaming": True,
        }
        if self.config.model:
            session_config["model"] = self.config.model
        if self.config.system_prompt:
            session_config["system_message"] = {"mode": "append", "content": self.config.system_prompt}

        self._session: Any = await self._client.create_session(session_config)
        self._session.on(self._handle_event)
        self._log("info", "copilot provider ready", model=self.config.model)

    async def send_initial_turn(self) -> None:
        if not self.config.system_prompt:
            return
        self._publish({"type": "thinking", "content": ""})
        try:
            await self._session.send_and_wait({"prompt": "Begin."}, timeout=300)
            self._publish({"type": "turn_complete"})
        except Exception as e:
            self._publish({"type": "error", "message": str(e)})
            self._log("error", "Initial LLM turn failed", error=str(e))

    async def send_message(self, text: str) -> None:
        self._publish({"type": "thinking", "content": ""})
        try:
            await self._session.send_and_wait({"prompt": text}, timeout=300)
            self._publish({"type": "turn_complete"})
        except Exception as e:
            self._publish({"type": "error", "message": str(e)})
            self._log("error", "LLM call failed", error=str(e))

    async def stop(self) -> None:
        sess = getattr(self, "_session", None)
        if sess:
            try:
                await sess.disconnect()
            except Exception:
                pass
        client = getattr(self, "_client", None)
        if client:
            try:
                await client.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------

    def _handle_event(self, event: Any) -> None:
        from copilot.generated.session_events import SessionEventType  # optional external dep

        t = event.type
        d = event.data
        try:
            if t == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                self._publish({"type": "delta", "content": d.delta_content or ""})
            elif t == SessionEventType.ASSISTANT_MESSAGE:
                self._publish({"type": "message", "content": d.content or ""})
            elif t == SessionEventType.TOOL_EXECUTION_START:
                self._publish(
                    {
                        "type": "tool_start",
                        "tool_name": d.tool_name or "",
                        "arguments": str(d.arguments) if d.arguments else "",
                    }
                )
            elif t == SessionEventType.TOOL_EXECUTION_COMPLETE:
                result_text = ""
                if d.result and hasattr(d.result, "content"):
                    result_text = str(d.result.content)[:500]
                self._publish({"type": "tool_complete", "tool_name": d.tool_name or "", "result": result_text})
            elif t == SessionEventType.ASSISTANT_USAGE:
                self._publish(
                    {
                        "type": "usage",
                        "input_tokens": d.input_tokens,
                        "output_tokens": d.output_tokens,
                        "model": d.model or self.config.model,
                        "timestamp": time.time(),
                    }
                )
            elif t == SessionEventType.SESSION_ERROR:
                self._publish({"type": "error", "message": d.message or "Unknown error"})
                self._log("error", "session error", error=d.message)
        except Exception:
            logger.exception("Error processing copilot event")
