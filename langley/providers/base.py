"""Abstract base class for LLM provider adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ProviderConfig:
    """Static configuration for an LLM provider, derived from the agent profile."""

    provider: str
    model: str = ""
    system_prompt: str = ""
    base_url: str = ""
    api_key: str = ""


# Callback signatures the runner injects into a provider.
PublishFn = Callable[[dict[str, Any]], None]
LogFn = Callable[..., None]  # log(level, message, **kwargs)


class LLMProvider(ABC):
    """Bridges a single LLM backend with the agent runner.

    Providers are instantiated by the runner with a :class:`ProviderConfig`
    plus two callbacks:

    * ``publish(body)`` — emit an outbox event (delta / message / tool_* / usage / error)
    * ``log(level, message, **kwargs)`` — structured log via the agent SDK

    The runner calls :meth:`start`, optionally :meth:`send_initial_turn`,
    repeatedly :meth:`send_message`, and finally :meth:`stop`.
    """

    def __init__(self, config: ProviderConfig, publish: PublishFn, log: LogFn) -> None:
        self.config = config
        self._publish = publish
        self._log = log

    @abstractmethod
    async def start(self) -> None:
        """Initialise any underlying client / session."""

    @abstractmethod
    async def send_message(self, text: str) -> None:
        """Forward a user message and stream the response via ``publish``."""

    async def send_initial_turn(self) -> None:
        """Optionally produce an initial response from the system prompt.

        Default is a no-op; providers that want to greet the user on launch
        should override this.
        """
        return None

    @abstractmethod
    async def stop(self) -> None:
        """Tear down the provider."""
