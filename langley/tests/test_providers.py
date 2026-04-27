"""Tests for langley.providers (OpenAI-compatible provider + dispatch)."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from langley.providers import ProviderConfig, get_provider
from langley.providers.base import LLMProvider
from langley.providers.openai_compatible import OpenAICompatibleProvider, _iter_sse


class TestSSEParser:
    def test_parses_data_lines(self):
        lines = [
            b'data: {"a": 1}\n',
            b"\n",
            b'data: {"b": 2}\n',
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]
        events = list(_iter_sse(iter(lines)))
        assert events == ['{"a": 1}', '{"b": 2}', "[DONE]"]

    def test_ignores_comments_and_blank(self):
        lines = [b": keepalive\n", b"\n", b'data: {"x": 1}\n', b"\n"]
        events = list(_iter_sse(iter(lines)))
        assert events == ['{"x": 1}']

    def test_handles_missing_trailing_blank(self):
        lines = [b'data: {"x": 1}\n']
        events = list(_iter_sse(iter(lines)))
        assert events == ['{"x": 1}']


class TestProviderDispatch:
    def test_resolves_lmstudio_alias(self):
        assert get_provider("lmstudio") is OpenAICompatibleProvider
        assert get_provider("openai-compatible") is OpenAICompatibleProvider
        assert get_provider("LM-Studio") is OpenAICompatibleProvider

    def test_unknown_provider_raises(self):
        with pytest.raises(KeyError):
            get_provider("nonexistent-provider-xyz")


class _StubHandler(BaseHTTPRequestHandler):
    """Minimal LM Studio-style chat completions stub."""

    chunks: list[str] = []

    def log_message(self, *args, **kwargs):  # silence
        pass

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in self.chunks:
            self.wfile.write(f"data: {c}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture
def stub_server():
    chunks = [
        json.dumps({"choices": [{"delta": {"content": "Hello"}}]}),
        json.dumps({"choices": [{"delta": {"content": " world"}}]}),
        json.dumps({"choices": [{"delta": {}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}, "model": "stub-model"}),
    ]
    _StubHandler.chunks = chunks
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()
    thread.join(timeout=2)


class TestOpenAICompatibleProvider:
    def test_streams_deltas_and_emits_message(self, stub_server: str):
        events: list[dict] = []
        logs: list[tuple] = []

        config = ProviderConfig(
            provider="lmstudio",
            model="stub-model",
            system_prompt="You are helpful.",
            base_url=stub_server,
        )
        provider: LLMProvider = OpenAICompatibleProvider(
            config,
            publish=events.append,
            log=lambda level, msg, **kw: logs.append((level, msg, kw)),
        )

        async def run() -> None:
            await provider.start()
            await provider.send_message("Hi!")
            await provider.stop()

        asyncio.run(run())

        types = [e["type"] for e in events]
        assert "thinking" in types
        assert types.count("delta") == 2
        deltas = [e["content"] for e in events if e["type"] == "delta"]
        assert "".join(deltas) == "Hello world"
        msg_events = [e for e in events if e["type"] == "message"]
        assert msg_events and msg_events[0]["content"] == "Hello world"
        usage_events = [e for e in events if e["type"] == "usage"]
        assert usage_events
        assert usage_events[0]["input_tokens"] == 3
        assert usage_events[0]["output_tokens"] == 2
        assert events[-1]["type"] == "turn_complete"

    def test_requires_base_url(self):
        # A non-lmstudio openai-compatible provider must error without a base_url.
        provider = OpenAICompatibleProvider(
            ProviderConfig(provider="openai-compatible", model="m"),
            publish=lambda b: None,
            log=lambda *a, **k: None,
        )
        with pytest.raises(RuntimeError, match="base_url"):
            asyncio.run(provider.start())

    def test_lmstudio_defaults_base_url(self):
        # Running an "lmstudio" agent with no base_url should fall back to
        # the well-known local default rather than failing.
        provider = OpenAICompatibleProvider(
            ProviderConfig(provider="lmstudio", model="m"),
            publish=lambda b: None,
            log=lambda *a, **k: None,
        )
        # start() will try to connect; we don't care, just that it doesn't
        # raise the "requires base_url" error and that base_url got set.
        try:
            asyncio.run(provider.start())
        except RuntimeError as e:
            assert "base_url" not in str(e)
        assert provider.config.base_url == "http://127.0.0.1:1234/v1"

    def test_requires_model(self):
        provider = OpenAICompatibleProvider(
            ProviderConfig(provider="lmstudio", base_url="http://x"),
            publish=lambda b: None,
            log=lambda *a, **k: None,
        )
        with pytest.raises(RuntimeError, match="model"):
            asyncio.run(provider.start())
