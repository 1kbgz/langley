"""State store interface and SQLite-backed implementation."""

import abc
import json
import sqlite3
from pathlib import Path
from typing import Any

from langley.models import CheckpointData


class StateStore(abc.ABC):
    """Interface for persisting agent state, checkpoints, and metadata."""

    @abc.abstractmethod
    def save_checkpoint(self, checkpoint: CheckpointData) -> None:
        """Save an agent state checkpoint."""

    @abc.abstractmethod
    def load_checkpoint(self, agent_id: str) -> CheckpointData | None:
        """Load the latest checkpoint for an agent. Returns None if no checkpoint exists."""

    @abc.abstractmethod
    def list_checkpoints(self, agent_id: str) -> list[CheckpointData]:
        """List all checkpoints for an agent, ordered by sequence descending."""

    @abc.abstractmethod
    def delete_checkpoints(self, agent_id: str, keep_latest: int = 0) -> int:
        """Delete checkpoints for an agent. If keep_latest > 0, retain that many most recent.
        Returns the number of checkpoints deleted."""

    @abc.abstractmethod
    def save_metadata(self, agent_id: str, tenant_id: str, key: str, value: Any) -> None:
        """Save a metadata key-value pair for an agent."""

    @abc.abstractmethod
    def get_metadata(self, agent_id: str, key: str) -> Any | None:
        """Get a metadata value for an agent. Returns None if not found."""

    @abc.abstractmethod
    def query_metadata(self, tenant_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Query metadata entries for a tenant, optionally filtered."""

    @abc.abstractmethod
    def close(self) -> None:
        """Clean up resources."""


class SqliteStateStore(StateStore):
    """SQLite-backed state store for checkpoints and metadata."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                state BLOB NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                sequence INTEGER NOT NULL DEFAULT 0,
                machine_id TEXT NOT NULL DEFAULT '',
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoints_agent
                ON checkpoints(agent_id);
            CREATE INDEX IF NOT EXISTS idx_checkpoints_tenant
                ON checkpoints(tenant_id);

            CREATE TABLE IF NOT EXISTS agent_metadata (
                agent_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (agent_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_metadata_tenant
                ON agent_metadata(tenant_id);
        """)

    def save_checkpoint(self, checkpoint: CheckpointData) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO checkpoints
               (id, agent_id, tenant_id, state, metadata, sequence, machine_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                checkpoint.id,
                checkpoint.agent_id,
                checkpoint.tenant_id,
                checkpoint.state,
                json.dumps(checkpoint.metadata),
                checkpoint.sequence,
                checkpoint.machine_id,
                checkpoint.timestamp,
            ),
        )
        self._conn.commit()

    def load_checkpoint(self, agent_id: str) -> CheckpointData | None:
        row = self._conn.execute(
            """SELECT id, agent_id, tenant_id, state, metadata, sequence, machine_id, timestamp
               FROM checkpoints WHERE agent_id = ? ORDER BY sequence DESC, timestamp DESC LIMIT 1""",
            (agent_id,),
        ).fetchone()
        if row is None:
            return None
        return CheckpointData(
            agent_id=row[1],
            tenant_id=row[2],
            state=row[3],
            metadata=json.loads(row[4]),
            id=row[0],
            sequence=row[5],
            machine_id=row[6],
            timestamp=row[7],
        )

    def list_checkpoints(self, agent_id: str) -> list[CheckpointData]:
        rows = self._conn.execute(
            """SELECT id, agent_id, tenant_id, state, metadata, sequence, machine_id, timestamp
               FROM checkpoints WHERE agent_id = ? ORDER BY sequence DESC, timestamp DESC""",
            (agent_id,),
        ).fetchall()
        return [
            CheckpointData(
                agent_id=r[1],
                tenant_id=r[2],
                state=r[3],
                metadata=json.loads(r[4]),
                id=r[0],
                sequence=r[5],
                machine_id=r[6],
                timestamp=r[7],
            )
            for r in rows
        ]

    def delete_checkpoints(self, agent_id: str, keep_latest: int = 0) -> int:
        if keep_latest > 0:
            # Get IDs to keep
            keep_ids = [
                r[0]
                for r in self._conn.execute(
                    """SELECT id FROM checkpoints WHERE agent_id = ?
                       ORDER BY sequence DESC, timestamp DESC LIMIT ?""",
                    (agent_id, keep_latest),
                ).fetchall()
            ]
            if not keep_ids:
                return 0
            placeholders = ",".join("?" for _ in keep_ids)
            cursor = self._conn.execute(
                f"DELETE FROM checkpoints WHERE agent_id = ? AND id NOT IN ({placeholders})",
                [agent_id, *keep_ids],
            )
        else:
            cursor = self._conn.execute("DELETE FROM checkpoints WHERE agent_id = ?", (agent_id,))
        self._conn.commit()
        return cursor.rowcount

    def save_metadata(self, agent_id: str, tenant_id: str, key: str, value: Any) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO agent_metadata (agent_id, tenant_id, key, value)
               VALUES (?, ?, ?, ?)""",
            (agent_id, tenant_id, key, json.dumps(value)),
        )
        self._conn.commit()

    def get_metadata(self, agent_id: str, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value FROM agent_metadata WHERE agent_id = ? AND key = ?",
            (agent_id, key),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def query_metadata(self, tenant_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT agent_id, tenant_id, key, value FROM agent_metadata WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchall()
        results = [{"agent_id": r[0], "tenant_id": r[1], "key": r[2], "value": json.loads(r[3])} for r in rows]
        if filters:
            for fk, fv in filters.items():
                results = [r for r in results if r.get(fk) == fv]
        return results

    def close(self) -> None:
        self._conn.close()
