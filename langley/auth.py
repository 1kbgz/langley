"""Auth provider interface and local file-backed implementation."""

import abc
import hashlib
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from langley.models import Identity


class AuthProvider(abc.ABC):
    """Interface for authentication and authorization."""

    @abc.abstractmethod
    def create_user(self, tenant_id: str, username: str, password: str, roles: list[str] | None = None) -> Identity:
        """Create a new user. Raises ValueError if user already exists."""

    @abc.abstractmethod
    def authenticate(self, tenant_id: str, username: str, password: str) -> Identity | None:
        """Authenticate a user. Returns Identity on success, None on failure."""

    @abc.abstractmethod
    def authorize(self, identity: Identity, action: str, resource: str = "*") -> bool:
        """Check if an identity is authorized for an action on a resource."""

    @abc.abstractmethod
    def get_user(self, tenant_id: str, username: str) -> Identity | None:
        """Get a user's identity. Returns None if not found."""

    @abc.abstractmethod
    def list_users(self, tenant_id: str) -> list[Identity]:
        """List all users for a tenant."""

    @abc.abstractmethod
    def delete_user(self, tenant_id: str, username: str) -> bool:
        """Delete a user. Returns True if deleted, False if not found."""

    @abc.abstractmethod
    def update_roles(self, tenant_id: str, username: str, roles: list[str]) -> Identity | None:
        """Update a user's roles. Returns updated Identity or None if not found."""

    @abc.abstractmethod
    def close(self) -> None:
        """Clean up resources."""


# Role hierarchy: admin > operator > viewer
_ROLE_ACTIONS: dict[str, set[str]] = {
    "admin": {"admin", "operate", "view"},
    "operator": {"operate", "view"},
    "viewer": {"view"},
}


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Hash a password with PBKDF2-HMAC-SHA256. Returns (hash_hex, salt_hex)."""
    if salt is None:
        salt = secrets.token_bytes(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return dk.hex(), salt.hex()


def _verify_password(password: str, password_hash: str, salt_hex: str) -> bool:
    """Verify a password against a stored hash and salt."""
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 100_000)
    return secrets.compare_digest(dk.hex(), password_hash)


class LocalAuthProvider(AuthProvider):
    """SQLite-backed local authentication provider.

    Uses PBKDF2-HMAC-SHA256 for password hashing.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                roles TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(tenant_id, username)
            );
        """)

    def create_user(self, tenant_id: str, username: str, password: str, roles: list[str] | None = None) -> Identity:
        if roles is None:
            roles = ["viewer"]
        user_id = secrets.token_hex(16)
        pw_hash, salt = _hash_password(password)
        try:
            self._conn.execute(
                """INSERT INTO users (user_id, tenant_id, username, password_hash, salt, roles)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, tenant_id, username, pw_hash, salt, json.dumps(roles)),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"User '{username}' already exists in tenant '{tenant_id}'")
        return Identity(user_id=user_id, tenant_id=tenant_id, username=username, roles=roles)

    def authenticate(self, tenant_id: str, username: str, password: str) -> Identity | None:
        row = self._conn.execute(
            "SELECT user_id, password_hash, salt, roles, active FROM users WHERE tenant_id = ? AND username = ?",
            (tenant_id, username),
        ).fetchone()
        if row is None:
            return None
        user_id, pw_hash, salt, roles_json, active = row
        if not active:
            return None
        if not _verify_password(password, pw_hash, salt):
            return None
        return Identity(
            user_id=user_id,
            tenant_id=tenant_id,
            username=username,
            roles=json.loads(roles_json),
        )

    def authorize(self, identity: Identity, action: str, resource: str = "*") -> bool:
        for role in identity.roles:
            allowed = _ROLE_ACTIONS.get(role, set())
            if action in allowed:
                return True
        return False

    def get_user(self, tenant_id: str, username: str) -> Identity | None:
        row = self._conn.execute(
            "SELECT user_id, roles, metadata FROM users WHERE tenant_id = ? AND username = ? AND active = 1",
            (tenant_id, username),
        ).fetchone()
        if row is None:
            return None
        return Identity(
            user_id=row[0],
            tenant_id=tenant_id,
            username=username,
            roles=json.loads(row[1]),
            metadata=json.loads(row[2]),
        )

    def list_users(self, tenant_id: str) -> list[Identity]:
        rows = self._conn.execute(
            "SELECT user_id, username, roles, metadata FROM users WHERE tenant_id = ? AND active = 1",
            (tenant_id,),
        ).fetchall()
        return [
            Identity(
                user_id=r[0],
                tenant_id=tenant_id,
                username=r[1],
                roles=json.loads(r[2]),
                metadata=json.loads(r[3]),
            )
            for r in rows
        ]

    def delete_user(self, tenant_id: str, username: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM users WHERE tenant_id = ? AND username = ?",
            (tenant_id, username),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def update_roles(self, tenant_id: str, username: str, roles: list[str]) -> Identity | None:
        cursor = self._conn.execute(
            "UPDATE users SET roles = ? WHERE tenant_id = ? AND username = ? AND active = 1",
            (json.dumps(roles), tenant_id, username),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_user(tenant_id, username)

    def close(self) -> None:
        self._conn.close()
