"""Langley configuration — file-backed settings with CLI override support.

Looks for configuration in order:
1. Path passed via --config
2. ./langley.cfg
3. ~/.langley.cfg

Uses Python's configparser (INI-style) format.
"""

import configparser
from pathlib import Path

# Default configuration values
DEFAULTS: dict[str, dict[str, str]] = {
    "server": {
        "host": "127.0.0.1",
        "port": "8000",
        "data_dir": ".langley",
    },
    "auth": {
        "provider": "none",
    },
}


def _default_search_paths() -> list[Path]:
    """Return config file search paths in priority order."""
    return [
        Path("langley.cfg"),
        Path.home() / ".langley.cfg",
    ]


def load_config(path: str | Path | None = None) -> configparser.ConfigParser:
    """Load configuration from a file.

    If *path* is given, only that file is tried (raises FileNotFoundError
    if missing).  Otherwise the default search paths are tried in order
    and the first found is used.  If none exist, an empty config with
    built-in defaults is returned.
    """
    cp = configparser.ConfigParser()
    # Seed defaults
    for section, values in DEFAULTS.items():
        cp[section] = values

    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        cp.read(str(p))
    else:
        for candidate in _default_search_paths():
            if candidate.is_file():
                cp.read(str(candidate))
                break

    return cp
