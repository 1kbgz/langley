"""LLM provider adapters used by the built-in ``langley.agent_runner``.

Each provider implements the :class:`LLMProvider` interface so the runner can
talk to any backend (GitHub Copilot, an OpenAI-compatible server such as LM
Studio, an opencode session server, etc.) through a uniform API.
"""

from langley.providers.base import LLMProvider, ProviderConfig
from langley.providers.openai_compatible import OpenAICompatibleProvider


def get_provider(name: str) -> type[LLMProvider]:
    """Return the provider class registered for ``name``.

    Falls back to :class:`OpenAICompatibleProvider` for ``openai-compatible``,
    ``lmstudio``, and similar OpenAI-shaped backends.

    Raises:
        KeyError: If no provider is registered for ``name``.
    """
    key = name.strip().lower()
    if key in {"openai-compatible", "openai_compatible", "lmstudio", "lm-studio", "lm_studio"}:
        return OpenAICompatibleProvider
    if key in {"github-copilot", "copilot"}:
        # Imported lazily to avoid hard dependency on the optional copilot SDK.
        from langley.providers.copilot import CopilotProvider

        return CopilotProvider
    raise KeyError(f"Unknown LLM provider: {name!r}")


__all__ = ["LLMProvider", "ProviderConfig", "OpenAICompatibleProvider", "get_provider"]
