"""OpenAI-compatible chat-completions provider.

Talks to any server that implements ``POST /v1/chat/completions`` with
streaming via Server-Sent Events.  Tested against LM Studio (default
``http://localhost:1234/v1``) and the Ollama OpenAI compatibility shim.

The implementation deliberately uses only the Python standard library so
langley keeps its "no heavy required dependencies" guarantee.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator

from langley.providers.base import LLMProvider

_DEFAULT_TIMEOUT = 300

# Reasonable default for the well-known LM Studio local server. Used when
# the profile (or env) doesn't specify a base_url so users can run an
# LM Studio agent with zero configuration.
_LMSTUDIO_DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
_LMSTUDIO_ALIASES = {"lmstudio", "lm-studio", "lm_studio"}


class OpenAICompatibleProvider(LLMProvider):
    """Streams chat completions from an OpenAI-compatible HTTP endpoint."""

    async def start(self) -> None:
        if not self.config.base_url:
            if self.config.provider.strip().lower() in _LMSTUDIO_ALIASES:
                self.config.base_url = _LMSTUDIO_DEFAULT_BASE_URL
                self._log(
                    "info",
                    "no base_url configured; defaulting to LM Studio at " + _LMSTUDIO_DEFAULT_BASE_URL,
                )
            else:
                raise RuntimeError("OpenAICompatibleProvider requires base_url to be set on the profile")
        if not self.config.model:
            raise RuntimeError("OpenAICompatibleProvider requires model to be set on the profile")

        # Conversation history shared across turns.
        self._history: list[dict[str, str]] = []
        if self.config.system_prompt:
            self._history.append({"role": "system", "content": self.config.system_prompt})

        self._log("info", "openai-compatible provider ready", base_url=self.config.base_url, model=self.config.model)

    async def send_initial_turn(self) -> None:
        # Don't auto-prompt: many local models are slow / expensive to warm up,
        # and an unsolicited "Begin." turn just produces noise.  The user's
        # first chat message will drive the first request.
        return None

    async def send_message(self, text: str) -> None:
        await self._do_turn(text)

    async def stop(self) -> None:
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_turn(self, user_text: str) -> None:
        self._history.append({"role": "user", "content": user_text})
        self._publish({"type": "thinking", "content": ""})

        assistant_text_parts: list[str] = []
        try:
            # Run the blocking SSE loop in a worker thread so we don't block
            # the runner's event loop / inbox polling.
            await asyncio.to_thread(self._stream_completion, assistant_text_parts)
            full = "".join(assistant_text_parts)
            if full:
                self._history.append({"role": "assistant", "content": full})
                self._publish({"type": "message", "content": full})
            self._publish({"type": "turn_complete"})
        except Exception as exc:
            self._publish({"type": "error", "message": str(exc)})
            self._log("error", "openai-compatible turn failed", error=str(exc))

    def _stream_completion(self, assistant_text_parts: list[str]) -> None:
        """Synchronous worker: opens an SSE stream and pushes deltas."""
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": list(self._history),
            "stream": True,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500] if e.fp else ""
            raise RuntimeError(f"HTTP {e.code} from {url}: {detail}") from e

        with resp:
            for event in _iter_sse(resp):
                if event == "[DONE]":
                    break
                try:
                    obj = json.loads(event)
                except json.JSONDecodeError:
                    continue
                self._handle_chunk(obj, assistant_text_parts)

    def _handle_chunk(self, obj: dict[str, Any], assistant_text_parts: list[str]) -> None:
        choices = obj.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                assistant_text_parts.append(content)
                self._publish({"type": "delta", "content": content})

            tool_calls = delta.get("tool_calls") or []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or ""
                if name:
                    self._publish({"type": "tool_start", "tool_name": name, "arguments": str(args)})

        usage = obj.get("usage")
        if usage:
            self._publish(
                {
                    "type": "usage",
                    "input_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                    "model": obj.get("model") or self.config.model,
                    "timestamp": time.time(),
                }
            )


def _iter_sse(stream: Any) -> Iterator[str]:
    """Yield ``data:`` payloads from a Server-Sent-Events byte stream.

    The terminating ``[DONE]`` sentinel is yielded literally so callers can
    detect end-of-stream.  Multi-line ``data:`` fields are concatenated with
    newlines per the SSE spec.
    """
    buf: list[str] = []
    for raw in stream:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            if buf:
                yield "\n".join(buf)
                buf = []
            continue
        if line.startswith(":"):
            # SSE comment / keep-alive
            continue
        if line.startswith("data:"):
            buf.append(line[5:].lstrip())
    if buf:
        yield "\n".join(buf)
