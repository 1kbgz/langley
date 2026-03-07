"""Tenant manager interface and local SQLite-backed implementation."""

import abc
import json
import sqlite3
from pathlib import Path
from typing import Any

from langley.models import Tenant, _new_id, _now


class TenantManager(abc.ABC):
    """Interface for tenant CRUD and isolation boundaries."""

    @abc.abstractmethod
    def create_tenant(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        resource_quotas: dict[str, Any] | None = None,
    ) -> Tenant:
        """Create a new tenant. Raises ValueError if name already exists."""

    @abc.abstractmethod
    def get_tenant(self, tenant_id: str) -> Tenant | None:
        """Get a tenant by ID. Returns None if not found."""

    @abc.abstractmethod
    def get_tenant_by_name(self, name: str) -> Tenant | None:
        """Get a tenant by name. Returns None if not found."""

    @abc.abstractmethod
    def list_tenants(self, active_only: bool = True) -> list[Tenant]:
        """List all tenants."""

    @abc.abstractmethod
    def update_tenant(
        self,
        tenant_id: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        resource_quotas: dict[str, Any] | None = None,
    ) -> Tenant | None:
        """Update a tenant. Returns the updated tenant or None if not found."""

    @abc.abstractmethod
    def suspend_tenant(self, tenant_id: str) -> bool:
        """Suspend a tenant. Returns True if suspended, False if not found."""

    @abc.abstractmethod
    def activate_tenant(self, tenant_id: str) -> bool:
        """Activate a suspended tenant. Returns True if activated, False if not found."""

    @abc.abstractmethod
    def delete_tenant(self, tenant_id: str) -> bool:
        """Delete a tenant. Returns True if deleted, False if not found."""

    @abc.abstractmethod
    def close(self) -> None:
        """Clean up resources."""


class LocalTenantManager(TenantManager):
    """SQLite-backed tenant manager."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                metadata TEXT NOT NULL DEFAULT '{}',
                resource_quotas TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
        """)

    def _row_to_tenant(self, row: tuple) -> Tenant:
        return Tenant(
            name=row[1],
            id=row[0],
            active=bool(row[2]),
            metadata=json.loads(row[3]),
            resource_quotas=json.loads(row[4]),
            created_at=row[5],
        )

    def create_tenant(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        resource_quotas: dict[str, Any] | None = None,
    ) -> Tenant:
        tenant = Tenant(
            name=name,
            id=_new_id(),
            metadata=metadata or {},
            resource_quotas=resource_quotas or {},
            created_at=_now(),
        )
        try:
            self._conn.execute(
                """INSERT INTO tenants (id, name, active, metadata, resource_quotas, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    tenant.id,
                    tenant.name,
                    int(tenant.active),
                    json.dumps(tenant.metadata),
                    json.dumps(tenant.resource_quotas),
                    tenant.created_at,
                ),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Tenant with name '{name}' already exists")
        return tenant

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        row = self._conn.execute(
            "SELECT id, name, active, metadata, resource_quotas, created_at FROM tenants WHERE id = ?",
            (tenant_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_tenant(row)

    def get_tenant_by_name(self, name: str) -> Tenant | None:
        row = self._conn.execute(
            "SELECT id, name, active, metadata, resource_quotas, created_at FROM tenants WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_tenant(row)

    def list_tenants(self, active_only: bool = True) -> list[Tenant]:
        if active_only:
            rows = self._conn.execute(
                "SELECT id, name, active, metadata, resource_quotas, created_at FROM tenants WHERE active = 1"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, name, active, metadata, resource_quotas, created_at FROM tenants"
            ).fetchall()
        return [self._row_to_tenant(r) for r in rows]

    def update_tenant(
        self,
        tenant_id: str,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        resource_quotas: dict[str, Any] | None = None,
    ) -> Tenant | None:
        existing = self.get_tenant(tenant_id)
        if existing is None:
            return None

        updates: list[str] = []
        params: list[Any] = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))
        if resource_quotas is not None:
            updates.append("resource_quotas = ?")
            params.append(json.dumps(resource_quotas))

        if not updates:
            return existing

        params.append(tenant_id)
        sql = f"UPDATE tenants SET {', '.join(updates)} WHERE id = ?"
        try:
            self._conn.execute(sql, params)
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Tenant with name '{name}' already exists")
        return self.get_tenant(tenant_id)

    def suspend_tenant(self, tenant_id: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE tenants SET active = 0 WHERE id = ? AND active = 1",
            (tenant_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def activate_tenant(self, tenant_id: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE tenants SET active = 1 WHERE id = ? AND active = 0",
            (tenant_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_tenant(self, tenant_id: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM tenants WHERE id = ?",
            (tenant_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        self._conn.close()
