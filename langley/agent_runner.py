"""Built-in LLM agent runner.

Spawned automatically by the supervisor when a profile has ``llm_provider``
set and no explicit ``command``.  Reads configuration from environment
variables, loads the matching :mod:`langley.providers` adapter, and bridges
the langley message transport with the LLM conversation loop.

Env vars (set by the supervisor):
    LANGLEY_AGENT_ID, LANGLEY_TENANT_ID, LANGLEY_PROFILE_ID,
    LANGLEY_PROFILE_NAME, LANGLEY_TRANSPORT_DIR,
    LANGLEY_LLM_PROVIDER, LANGLEY_MODEL, LANGLEY_SYSTEM_PROMPT,
    LANGLEY_LLM_BASE_URL, LANGLEY_LLM_API_KEY
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from typing import Any

from langley.agent import AgentSDK
from langley.providers import ProviderConfig, get_provider

logger = logging.getLogger(__name__)


class AgentRunner:
    """Bridges an :class:`~langley.providers.base.LLMProvider` with langley's message transport."""

    def __init__(self) -> None:
        self.agent_id = os.environ["LANGLEY_AGENT_ID"]
        self.tenant_id = os.environ.get("LANGLEY_TENANT_ID", "default")
        self.provider_name = os.environ.get("LANGLEY_LLM_PROVIDER", "")
        self.config = ProviderConfig(
            provider=self.provider_name,
            model=os.environ.get("LANGLEY_MODEL", ""),
            system_prompt=os.environ.get("LANGLEY_SYSTEM_PROMPT", ""),
            base_url=os.environ.get("LANGLEY_LLM_BASE_URL", ""),
            api_key=os.environ.get("LANGLEY_LLM_API_KEY", ""),
        )

        self._inbox = f"agent.{self.agent_id}.inbox"
        self._outbox = f"agent.{self.agent_id}.outbox"

        self._sdk: Any = None
        self._provider: Any = None
        self._shutdown = asyncio.Event()
        self._last_seq = 0

    async def start(self) -> None:
        self._sdk = AgentSDK.from_env()
        self._sdk.start_heartbeat(interval=5.0)
        self._sdk.log("info", "agent_runner starting", provider=self.provider_name, model=self.config.model)

        try:
            provider_cls = get_provider(self.provider_name)
            self._provider = provider_cls(self.config, self._publish_outbox, self._sdk.log)
            await self._provider.start()
        except Exception as exc:
            # Publish to outbox so the chat panel actually shows the failure
            # instead of the user staring at a silent dead agent.
            msg = f"Failed to start provider '{self.provider_name}': {exc}"
            self._sdk.log("error", msg)
            try:
                self._publish_outbox({"type": "error", "message": msg})
            except Exception:
                logger.exception("Failed to publish startup error")
            self._sdk.report_status({"state": "errored", "error": msg})
            raise

        self._sdk.log("info", "agent_runner ready")
        self._sdk.report_status({"state": "ready", "model": self.config.model, "provider": self.provider_name})

        # Greet from the system prompt if the provider supports it.
        await self._provider.send_initial_turn()

    def _publish_outbox(self, body: dict[str, Any]) -> None:
        body.setdefault("agent_id", self.agent_id)
        body.setdefault("timestamp", time.time())
        self._sdk.send(self._outbox, body)

    async def run(self) -> None:
        while not self._shutdown.is_set():
            try:
                messages = list(self._sdk.receive(self._inbox, from_seq=self._last_seq))
                for msg in messages:
                    self._last_seq = msg.sequence + 1
                    user_text = ""
                    if isinstance(msg.body, dict):
                        user_text = msg.body.get("text", msg.body.get("body", "")) or ""
                    elif isinstance(msg.body, str):
                        user_text = msg.body
                    if not user_text:
                        continue

                    self._sdk.log("info", "received user message", preview=user_text[:100])
                    await self._provider.send_message(user_text)
            except Exception:
                logger.exception("Error in agent runner loop")

            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def stop(self) -> None:
        self._shutdown.set()
        if self._provider:
            try:
                await self._provider.stop()
            except Exception:
                logger.exception("Error stopping provider")
        if self._sdk:
            self._sdk.log("info", "agent_runner stopped")
            self._sdk.close()


async def _main() -> None:
    runner = AgentRunner()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, runner._shutdown.set)

    await runner.start()
    try:
        await runner.run()
    finally:
        await runner.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(_main())
