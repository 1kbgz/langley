"""Audit log interface and SQLite-backed implementation."""

import abc
import json
import sqlite3
from pathlib import Path
from typing import Any

from langley.models import AuditEntry


class AuditLog(abc.ABC):
    """Interface for append-only audit/trace records."""

    @abc.abstractmethod
    def append(self, entry: AuditEntry) -> None:
        """Append an audit entry."""

    @abc.abstractmethod
    def query(
        self,
        tenant_id: str,
        agent_id: str | None = None,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        """Query audit entries with optional filters."""

    @abc.abstractmethod
    def count(
        self,
        tenant_id: str,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> int:
        """Count audit entries matching filters."""

    @abc.abstractmethod
    def recent(self, limit: int = 50) -> list[AuditEntry]:
        """Return the most recent audit entries across all tenants."""

    @abc.abstractmethod
    def close(self) -> None:
        """Clean up resources."""


class SqliteAuditLog(AuditLog):
    """SQLite-backed audit log."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_entries (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_tenant
                ON audit_entries(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_audit_agent
                ON audit_entries(agent_id);
            CREATE INDEX IF NOT EXISTS idx_audit_type
                ON audit_entries(event_type);
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON audit_entries(timestamp);
        """)

    def append(self, entry: AuditEntry) -> None:
        self._conn.execute(
            """INSERT INTO audit_entries (id, tenant_id, agent_id, event_type, payload, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.tenant_id,
                entry.agent_id,
                entry.event_type,
                json.dumps(entry.payload),
                entry.timestamp,
            ),
        )
        self._conn.commit()

    def query(
        self,
        tenant_id: str,
        agent_id: str | None = None,
        event_type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEntry]:
        sql = "SELECT id, tenant_id, agent_id, event_type, payload, timestamp FROM audit_entries WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]

        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if event_type is not None:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)
        if until is not None:
            sql += " AND timestamp <= ?"
            params.append(until)

        sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(sql, params).fetchall()
        return [
            AuditEntry(
                tenant_id=r[1],
                agent_id=r[2],
                event_type=r[3],
                payload=json.loads(r[4]),
                id=r[0],
                timestamp=r[5],
            )
            for r in rows
        ]

    def count(
        self,
        tenant_id: str,
        agent_id: str | None = None,
        event_type: str | None = None,
    ) -> int:
        sql = "SELECT COUNT(*) FROM audit_entries WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]

        if agent_id is not None:
            sql += " AND agent_id = ?"
            params.append(agent_id)
        if event_type is not None:
            sql += " AND event_type = ?"
            params.append(event_type)

        row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def recent(self, limit: int = 50) -> list[AuditEntry]:
        sql = "SELECT id, tenant_id, agent_id, event_type, payload, timestamp FROM audit_entries ORDER BY timestamp DESC LIMIT ?"
        rows = self._conn.execute(sql, (limit,)).fetchall()
        return [
            AuditEntry(
                tenant_id=r[1],
                agent_id=r[2],
                event_type=r[3],
                payload=json.loads(r[4]),
                id=r[0],
                timestamp=r[5],
            )
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
