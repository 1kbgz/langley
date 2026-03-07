"""Preconfigured agent discovery — scans well-known config directories.

Discovers agent profiles from ``~/.claude/agents/``, ``~/.copilot/agents/``,
``~/.gemini/agents/``, ``~/.langley/agents/`` and returns them as lightweight
descriptors that can be imported into langley's profile store.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Well-known directories → provider IDs
_DEFAULT_DIRS: dict[str, str] = {
    "~/.claude/agents": "anthropic",
    "~/.copilot/agents": "github-copilot",
    "~/.gemini/agents": "google",
    "~/.langley/agents": "langley",
}


@dataclass
class PreconfiguredAgent:
    """An agent profile discovered from a config directory."""

    name: str
    provider: str
    model: str = ""
    system_prompt: str = ""
    source: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_agent_file(path: Path, default_provider: str) -> PreconfiguredAgent | None:
    """Parse a single agent file (JSON, YAML, or TOML)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    data: dict[str, Any] = {}
    suffix = path.suffix.lower()

    try:
        if suffix in (".json",):
            data = json.loads(text)
        elif suffix in (".yaml", ".yml"):
            try:
                import yaml

                data = yaml.safe_load(text) or {}
            except ImportError:
                # PyYAML not installed — skip YAML files
                return None
        elif suffix in (".toml",):
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore[no-redef]
                except ImportError:
                    return None
            data = tomllib.loads(text)
        elif suffix in (".md",):
            # Markdown files with YAML frontmatter (e.g. Claude agent files)
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    try:
                        import yaml

                        data = yaml.safe_load(parts[1]) or {}
                    except ImportError:
                        return None
                    # The markdown body becomes the system prompt if not set
                    body = parts[2].strip()
                    if body and "system_prompt" not in data:
                        data["system_prompt"] = body
            else:
                # Plain markdown — treat as system prompt
                data = {"system_prompt": text.strip()}
        else:
            # Try JSON as fallback
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return None
    except (json.JSONDecodeError, ValueError):
        logger.debug("Failed to parse %s", path)
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name", path.stem)
    provider = data.get("provider", data.get("llm_provider", default_provider))
    model = data.get("model", "")
    system_prompt = data.get("system_prompt", data.get("instructions", ""))

    return PreconfiguredAgent(
        name=str(name),
        provider=str(provider),
        model=str(model),
        system_prompt=str(system_prompt)[:500],  # Truncate for listing
        source=str(path),
        config=data,
    )


def discover_agents(
    extra_dirs: list[str] | None = None,
) -> list[PreconfiguredAgent]:
    """Scan well-known directories and return discovered agent profiles.

    Parameters
    ----------
    extra_dirs:
        Additional ``dir:provider`` pairs to scan (from env or config).
    """
    dirs = dict(_DEFAULT_DIRS)

    # Add from LANGLEY_AGENT_DIRS env var (colon-separated dir=provider pairs)
    env_dirs = os.environ.get("LANGLEY_AGENT_DIRS", "")
    for entry in env_dirs.split(":"):
        entry = entry.strip()
        if "=" in entry:
            d, p = entry.split("=", 1)
            dirs[d.strip()] = p.strip()
        elif entry:
            dirs[entry] = "unknown"

    if extra_dirs:
        for entry in extra_dirs:
            if "=" in entry:
                d, p = entry.split("=", 1)
                dirs[d.strip()] = p.strip()
            else:
                dirs[entry] = "unknown"

    agents: list[PreconfiguredAgent] = []

    for dir_path, provider in dirs.items():
        expanded = Path(os.path.expanduser(dir_path))
        if not expanded.is_dir():
            continue

        for child in sorted(expanded.iterdir()):
            if child.is_file() and not child.name.startswith("."):
                agent = _parse_agent_file(child, provider)
                if agent is not None:
                    agents.append(agent)

    return agents


# -- Provider → default agents directory mapping --
_PROVIDER_DIRS: dict[str, str] = {
    "anthropic": "~/.claude/agents",
    "github-copilot": "~/.copilot/agents",
    "google": "~/.gemini/agents",
    "langley": "~/.langley/agents",
}


def default_agents_dir(provider: str) -> Path | None:
    """Return the well-known agents directory for *provider*, or ``None``."""
    raw = _PROVIDER_DIRS.get(provider)
    if raw is None:
        return None
    return Path(os.path.expanduser(raw))


def _profile_to_markdown(
    name: str,
    provider: str,
    model: str,
    system_prompt: str,
) -> str:
    """Serialise a profile as Markdown with YAML frontmatter."""
    lines = ["---"]
    lines.append(f"name: {name}")
    if provider:
        lines.append(f"provider: {provider}")
    if model:
        lines.append(f"model: {model}")
    lines.append("---")
    lines.append("")
    if system_prompt:
        lines.append(system_prompt)
    else:
        lines.append("")
    return "\n".join(lines)


def save_agent_to_disk(
    name: str,
    provider: str,
    model: str = "",
    system_prompt: str = "",
    path: str | None = None,
) -> str:
    """Write a profile to disk as Markdown with YAML frontmatter.

    Parameters
    ----------
    name:
        Agent name (also used as the filename when *path* is not given).
    provider:
        LLM provider id (used to determine default directory).
    model:
        Model id.
    system_prompt:
        System prompt / instructions.
    path:
        Explicit target file path.  If ``None`` the file is written to the
        provider's well-known agents directory (e.g. ``~/.copilot/agents/``).

    Returns
    -------
    str
        The absolute path of the written file.

    Raises
    ------
    ValueError
        If no path is given and no default directory is known for the provider.
    """
    if path:
        target = Path(os.path.expanduser(path))
    else:
        agents_dir = default_agents_dir(provider)
        if agents_dir is None:
            raise ValueError(f"No known agents directory for provider '{provider}'. Please specify an explicit path.")
        # Sanitise name for use as a filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
        target = agents_dir / f"{safe_name}.md"

    target.parent.mkdir(parents=True, exist_ok=True)
    content = _profile_to_markdown(name, provider, model, system_prompt)
    target.write_text(content, encoding="utf-8")
    return str(target)
