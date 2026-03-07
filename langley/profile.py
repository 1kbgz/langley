"""Profile management — load, validate, store, and version agent profiles.

Supports YAML, JSON, and TOML configuration files.  Provides a store-backed
CRUD layer with immutable versioning and a template/overlay mechanism.
"""

import copy
import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from typing import Any

from langley.models import AgentProfile, _new_id, _now


# ---------------------------------------------------------------------------
# File loaders
# ---------------------------------------------------------------------------

def _load_yaml(text: str) -> dict[str, Any]:
    """Load YAML text. Raises ImportError if pyyaml is not installed."""
    import yaml  # optional dependency
    return yaml.safe_load(text) or {}


def _load_toml(text: str) -> dict[str, Any]:
    """Load TOML text (Python >=3.11 ships tomllib)."""
    try:
        import tomllib  # stdlib 3.11+
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]  # optional fallback
    return tomllib.loads(text)


def _load_json(text: str) -> dict[str, Any]:
    return json.loads(text)


_LOADERS: dict[str, Any] = {
    ".yaml": _load_yaml,
    ".yml": _load_yaml,
    ".json": _load_json,
    ".toml": _load_toml,
}


def load_profile_from_file(path: str) -> AgentProfile:
    """Load an AgentProfile from a YAML, JSON, or TOML file."""
    ext = os.path.splitext(path)[1].lower()
    loader = _LOADERS.get(ext)
    if loader is None:
        raise ValueError(f"Unsupported profile file extension: {ext}")
    with open(path) as fh:
        data = loader(fh.read())
    return AgentProfile.from_dict(data)


def load_profile_from_string(text: str, fmt: str = "json") -> AgentProfile:
    """Load an AgentProfile from a string in the given format."""
    fmt = fmt.lower().lstrip(".")
    if fmt in ("yaml", "yml"):
        data = _load_yaml(text)
    elif fmt == "toml":
        data = _load_toml(text)
    elif fmt == "json":
        data = _load_json(text)
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    return AgentProfile.from_dict(data)


# ---------------------------------------------------------------------------
# Template / overlay mechanism
# ---------------------------------------------------------------------------

def merge_profiles(base: AgentProfile, overlay: dict[str, Any]) -> AgentProfile:
    """Create a new profile by shallow-merging *overlay* onto *base*.

    Dict fields (environment, resource_limits, tags) are merged via dict.update.
    List fields (command, tools, secrets) are replaced wholesale if present in
    the overlay.  Scalar fields are overwritten.
    """
    merged = base.to_dict()
    for key, value in overlay.items():
        if key not in merged:
            continue
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return AgentProfile.from_dict(merged)


# ---------------------------------------------------------------------------
# Profile Store interface + SQLite implementation
# ---------------------------------------------------------------------------

class ProfileStore(ABC):
    """Abstract CRUD interface for agent profiles with immutable versioning."""

    @abstractmethod
    def save(self, profile: AgentProfile) -> AgentProfile:
        """Save a profile. If a profile with the same id already exists,
        bump the version and store a new immutable snapshot."""

    @abstractmethod
    def get(self, profile_id: str, version: int | None = None) -> AgentProfile | None:
        """Retrieve a profile by id. If version is None, return the latest."""

    @abstractmethod
    def list_profiles(self, tenant_id: str | None = None) -> list[AgentProfile]:
        """List the latest version of every profile, optionally filtered by tenant."""

    @abstractmethod
    def list_versions(self, profile_id: str) -> list[AgentProfile]:
        """Return all immutable versions of a profile, oldest first."""

    @abstractmethod
    def delete(self, profile_id: str) -> bool:
        """Delete all versions of a profile. Returns True if it existed."""

    @abstractmethod
    def close(self) -> None: ...


class SqliteProfileStore(ProfileStore):
    """SQLite-backed profile store with immutable versioning."""

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id          TEXT NOT NULL,
                version     INTEGER NOT NULL,
                tenant_id   TEXT NOT NULL,
                data        TEXT NOT NULL,
                created_at  REAL NOT NULL,
                PRIMARY KEY (id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_profiles_tenant ON profiles(tenant_id);
        """)
        self._conn.commit()

    def save(self, profile: AgentProfile) -> AgentProfile:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(version) FROM profiles WHERE id = ?",
                (profile.id,),
            ).fetchone()
            max_ver = row[0] if row[0] is not None else 0
            new_ver = max_ver + 1
            saved = copy.copy(profile)
            saved.version = new_ver
            saved.created_at = _now()
            self._conn.execute(
                "INSERT INTO profiles (id, version, tenant_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (saved.id, saved.version, saved.tenant_id, json.dumps(saved.to_dict()), saved.created_at),
            )
            self._conn.commit()
        return saved

    def get(self, profile_id: str, version: int | None = None) -> AgentProfile | None:
        if version is not None:
            row = self._conn.execute(
                "SELECT data FROM profiles WHERE id = ? AND version = ?",
                (profile_id, version),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT data FROM profiles WHERE id = ? ORDER BY version DESC LIMIT 1",
                (profile_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentProfile.from_dict(json.loads(row[0]))

    def list_profiles(self, tenant_id: str | None = None) -> list[AgentProfile]:
        if tenant_id is not None:
            rows = self._conn.execute(
                """SELECT data FROM profiles p1
                   WHERE tenant_id = ? AND version = (
                       SELECT MAX(version) FROM profiles p2 WHERE p2.id = p1.id
                   )
                   ORDER BY created_at DESC""",
                (tenant_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT data FROM profiles p1
                   WHERE version = (
                       SELECT MAX(version) FROM profiles p2 WHERE p2.id = p1.id
                   )
                   ORDER BY created_at DESC""",
            ).fetchall()
        return [AgentProfile.from_dict(json.loads(r[0])) for r in rows]

    def list_versions(self, profile_id: str) -> list[AgentProfile]:
        rows = self._conn.execute(
            "SELECT data FROM profiles WHERE id = ? ORDER BY version ASC",
            (profile_id,),
        ).fetchall()
        return [AgentProfile.from_dict(json.loads(r[0])) for r in rows]

    def delete(self, profile_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
