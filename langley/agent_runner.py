"""Built-in LLM agent runner.

Spawned automatically by the supervisor when a profile has ``llm_provider``
set and no explicit ``command``.  Reads configuration from environment
variables, connects to the configured LLM via the Copilot SDK, and bridges
the langley message transport with the LLM conversation loop.

Env vars (set by the supervisor):
    LANGLEY_AGENT_ID, LANGLEY_TENANT_ID, LANGLEY_PROFILE_ID,
    LANGLEY_PROFILE_NAME, LANGLEY_TRANSPORT_DIR,
    LANGLEY_LLM_PROVIDER, LANGLEY_MODEL, LANGLEY_SYSTEM_PROMPT
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

# Copilot CLI path — prefer env override, then VS Code bundled location
_DEFAULT_COPILOT_CLI = os.environ.get(
    "LANGLEY_COPILOT_CLI_PATH",
    os.path.expanduser(
        "~/.config/Code/User/globalStorage/github.copilot-chat/copilotCli/copilot"
    ),
)


def _find_copilot_cli() -> str:
    """Locate the copilot CLI binary."""
    import shutil

    # Explicit override
    explicit = os.environ.get("LANGLEY_COPILOT_CLI_PATH")
    if explicit and os.path.isfile(explicit):
        return explicit

    # VS Code bundled
    if os.path.isfile(_DEFAULT_COPILOT_CLI):
        return _DEFAULT_COPILOT_CLI

    # System PATH
    on_path = shutil.which("copilot")
    if on_path:
        return on_path

    raise RuntimeError(
        "copilot CLI not found. Install GitHub Copilot in VS Code, "
        "or set LANGLEY_COPILOT_CLI_PATH."
    )


class AgentRunner:
    """Bridges a Copilot SDK session with langley's message transport."""

    def __init__(self) -> None:
        # Read config from env
        self.agent_id = os.environ["LANGLEY_AGENT_ID"]
        self.tenant_id = os.environ.get("LANGLEY_TENANT_ID", "default")
        self.provider = os.environ.get("LANGLEY_LLM_PROVIDER", "")
        self.model = os.environ.get("LANGLEY_MODEL", "")
        self.system_prompt = os.environ.get("LANGLEY_SYSTEM_PROMPT", "")

        self._inbox = f"agent.{self.agent_id}.inbox"
        self._outbox = f"agent.{self.agent_id}.outbox"
        self._logs = f"agent.{self.agent_id}.logs"

        self._sdk: Any = None        # langley AgentSDK
        self._client: Any = None     # CopilotClient
        self._session: Any = None    # CopilotSession
        self._shutdown = asyncio.Event()
        self._last_seq = 0

    async def start(self) -> None:
        """Initialise the langley SDK and Copilot session."""
        from langley.agent import AgentSDK

        self._sdk = AgentSDK.from_env()
        self._sdk.start_heartbeat(interval=5.0)

        self._sdk.log("info", "agent_runner starting", provider=self.provider, model=self.model)

        await self._init_copilot()

        self._sdk.log("info", "agent_runner ready")
        self._sdk.report_status({"state": "ready", "model": self.model, "provider": self.provider})

    async def _init_copilot(self) -> None:
        """Create a CopilotClient and session."""
        from copilot import CopilotClient, PermissionHandler
        from copilot.generated.session_events import SessionEventType

        cli_path = _find_copilot_cli()

        self._client = CopilotClient({"cli_path": cli_path})
        await self._client.start()

        session_config: dict[str, Any] = {
            "on_permission_request": PermissionHandler.approve_all,
            "streaming": True,
        }

        if self.model:
            session_config["model"] = self.model

        if self.system_prompt:
            session_config["system_message"] = {
                "mode": "append",
                "content": self.system_prompt,
            }

        self._session = await self._client.create_session(session_config)

        # Publish streaming events to the outbox
        def _on_event(event: Any) -> None:
            t = event.type
            d = event.data
            try:
                if t == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                    self._publish_outbox({
                        "type": "delta",
                        "content": d.delta_content or "",
                    })
                elif t == SessionEventType.ASSISTANT_MESSAGE:
                    self._publish_outbox({
                        "type": "message",
                        "content": d.content or "",
                    })
                elif t == SessionEventType.TOOL_EXECUTION_START:
                    self._publish_outbox({
                        "type": "tool_start",
                        "tool_name": d.tool_name or "",
                        "arguments": str(d.arguments) if d.arguments else "",
                    })
                elif t == SessionEventType.TOOL_EXECUTION_COMPLETE:
                    result_text = ""
                    if d.result and hasattr(d.result, "content"):
                        result_text = str(d.result.content)[:500]
                    self._publish_outbox({
                        "type": "tool_complete",
                        "tool_name": d.tool_name or "",
                        "result": result_text,
                    })
                elif t == SessionEventType.ASSISTANT_USAGE:
                    self._publish_outbox({
                        "type": "usage",
                        "input_tokens": d.input_tokens,
                        "output_tokens": d.output_tokens,
                        "model": d.model or self.model,
                    })
                elif t == SessionEventType.SESSION_ERROR:
                    self._publish_outbox({
                        "type": "error",
                        "message": d.message or "Unknown error",
                    })
                    self._sdk.log("error", "session error", error=d.message)
            except Exception:
                logger.exception("Error processing copilot event")

        self._session.on(_on_event)

    def _publish_outbox(self, body: dict[str, Any]) -> None:
        """Publish a message on this agent's outbox channel."""
        body["agent_id"] = self.agent_id
        body["timestamp"] = time.time()
        self._sdk.send(self._outbox, body)

    async def _send_to_llm(self, text: str) -> None:
        """Forward a user message to the Copilot session and wait for response."""
        self._publish_outbox({"type": "thinking", "content": ""})
        try:
            await self._session.send_and_wait({"prompt": text}, timeout=300)
            self._publish_outbox({"type": "turn_complete"})
        except Exception as e:
            self._publish_outbox({"type": "error", "message": str(e)})
            self._sdk.log("error", "LLM call failed", error=str(e))

    async def run(self) -> None:
        """Main loop: poll inbox for messages and forward to LLM."""
        while not self._shutdown.is_set():
            try:
                messages = list(self._sdk.receive(self._inbox, from_seq=self._last_seq))
                for msg in messages:
                    self._last_seq = msg.sequence + 1
                    user_text = msg.body.get("text", msg.body.get("body", ""))
                    if not user_text:
                        # Try the whole body as text if it's a string
                        if isinstance(msg.body, str):
                            user_text = msg.body
                        else:
                            continue

                    self._sdk.log("info", "received user message", preview=user_text[:100])
                    await self._send_to_llm(user_text)

            except Exception:
                logger.exception("Error in agent runner loop")

            # Poll interval
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        """Shut down the runner."""
        self._shutdown.set()
        if self._session:
            try:
                await self._session.disconnect()
            except Exception:
                pass
        if self._client:
            try:
                await self._client.stop()
            except Exception:
                pass
        if self._sdk:
            self._sdk.log("info", "agent_runner stopped")
            self._sdk.close()


async def _main() -> None:
    runner = AgentRunner()

    loop = asyncio.get_event_loop()

    def _signal_handler() -> None:
        runner._shutdown.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await runner.start()
    try:
        await runner.run()
    finally:
        await runner.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_main())
