"""Tests for langley.discovery — agent discovery and save-to-disk."""

import json
from pathlib import Path

import pytest

from langley.discovery import (
    PreconfiguredAgent,
    _parse_agent_file,
    _profile_to_markdown,
    default_agents_dir,
    discover_agents,
    save_agent_to_disk,
)


class TestPreconfiguredAgent:
    def test_to_dict(self):
        agent = PreconfiguredAgent(
            name="test-agent",
            provider="anthropic",
            model="claude-sonnet-4",
            system_prompt="You are helpful.",
            source="/tmp/agents/test-agent.json",
        )
        d = agent.to_dict()
        assert d["name"] == "test-agent"
        assert d["provider"] == "anthropic"
        assert d["model"] == "claude-sonnet-4"
        assert d["system_prompt"] == "You are helpful."


class TestParseAgentFile:
    def test_parse_json(self, tmp_path):
        f = tmp_path / "agent.json"
        f.write_text(json.dumps({"name": "json-agent", "model": "gpt-4o", "system_prompt": "hello"}))
        result = _parse_agent_file(f, "openai")
        assert result is not None
        assert result.name == "json-agent"
        assert result.model == "gpt-4o"
        assert result.provider == "openai"

    def test_parse_markdown_with_frontmatter(self, tmp_path):
        f = tmp_path / "agent.md"
        f.write_text("---\nname: md-agent\nmodel: claude-3\n---\nYou are a helper.")
        result = _parse_agent_file(f, "anthropic")
        assert result is not None
        assert result.name == "md-agent"
        assert result.system_prompt == "You are a helper."

    def test_parse_plain_markdown(self, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("Just a system prompt in markdown.")
        result = _parse_agent_file(f, "langley")
        assert result is not None
        assert result.name == "plain"  # stem
        assert result.system_prompt == "Just a system prompt in markdown."

    def test_parse_missing_file(self, tmp_path):
        result = _parse_agent_file(tmp_path / "nonexistent.json", "x")
        assert result is None

    def test_parse_unknown_extension_as_json(self, tmp_path):
        f = tmp_path / "agent.cfg"
        f.write_text(json.dumps({"name": "cfg-agent"}))
        result = _parse_agent_file(f, "custom")
        assert result is not None
        assert result.name == "cfg-agent"

    def test_parse_bad_json_returns_none(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all {{")
        result = _parse_agent_file(f, "x")
        assert result is None


class TestDiscoverAgents:
    def test_discovers_agents_from_dir(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / ".test-agents"
        agents_dir.mkdir()
        (agents_dir / "a.json").write_text(json.dumps({"name": "a"}))
        (agents_dir / "b.json").write_text(json.dumps({"name": "b"}))

        monkeypatch.setattr(
            "langley.discovery._DEFAULT_DIRS",
            {str(agents_dir): "test-provider"},
        )
        monkeypatch.delenv("LANGLEY_AGENT_DIRS", raising=False)

        agents = discover_agents()
        assert len(agents) == 2
        names = {a.name for a in agents}
        assert names == {"a", "b"}

    def test_returns_empty_for_nonexistent_dirs(self, monkeypatch):
        monkeypatch.setattr(
            "langley.discovery._DEFAULT_DIRS",
            {"/tmp/definitely-does-not-exist-abc123": "x"},
        )
        monkeypatch.delenv("LANGLEY_AGENT_DIRS", raising=False)
        assert discover_agents() == []


class TestDefaultAgentsDir:
    def test_known_provider(self):
        d = default_agents_dir("anthropic")
        assert d is not None
        assert str(d).endswith(".claude/agents")

    def test_unknown_provider(self):
        assert default_agents_dir("unknown-provider") is None


class TestProfileToMarkdown:
    def test_full_profile(self):
        md = _profile_to_markdown("my-agent", "anthropic", "claude-3", "Be helpful.")
        assert "---" in md
        assert "name: my-agent" in md
        assert "provider: anthropic" in md
        assert "model: claude-3" in md
        assert "Be helpful." in md

    def test_empty_prompt(self):
        md = _profile_to_markdown("x", "openai", "gpt-4o", "")
        assert "name: x" in md
        assert md.endswith("\n")


class TestSaveAgentToDisk:
    def test_save_with_explicit_path(self, tmp_path):
        target = str(tmp_path / "agents" / "saved.md")
        written = save_agent_to_disk(
            name="saved-agent",
            provider="openai",
            model="gpt-4o",
            system_prompt="Hello world",
            path=target,
        )
        assert written == target
        content = Path(target).read_text()
        assert "name: saved-agent" in content
        assert "Hello world" in content

    def test_save_to_default_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "langley.discovery._PROVIDER_DIRS",
            {"test-provider": str(tmp_path / ".test" / "agents")},
        )
        written = save_agent_to_disk(
            name="my agent",
            provider="test-provider",
            model="m1",
            system_prompt="prompt",
        )
        assert Path(written).exists()
        assert "my-agent.md" in written
        content = Path(written).read_text()
        assert "name: my agent" in content

    def test_save_raises_for_unknown_provider(self):
        with pytest.raises(ValueError, match="No known agents directory"):
            save_agent_to_disk(name="x", provider="bogus-provider-xyz")

    def test_save_creates_parent_dirs(self, tmp_path):
        target = str(tmp_path / "a" / "b" / "c" / "agent.md")
        written = save_agent_to_disk(
            name="deep",
            provider="openai",
            path=target,
        )
        assert Path(written).exists()
