"""Auth provider interface and implementations.

Implementations:
  - NoAuthProvider      — no authentication (default, open access)
  - LocalAuthProvider   — SQLite-backed with PBKDF2 password hashing
  - PamAuthProvider     — PAM-based login via ``pamela``
  - MacAuthProvider     — macOS OpenDirectory authentication
  - Win32AuthProvider   — Windows domain/local authentication
"""

import abc
import hashlib
import json
import logging
import secrets
import sqlite3
import sys
from pathlib import Path

from langley.models import Identity

logger = logging.getLogger(__name__)


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


# ── No-auth provider (default) ────────────────────────────────


class NoAuthProvider(AuthProvider):
    """Open-access provider — no authentication required.

    All operations succeed.  ``authenticate`` always returns an admin
    identity.  This is the default when no auth is configured.
    """

    def create_user(self, tenant_id: str, username: str, password: str, roles: list[str] | None = None) -> Identity:
        return Identity(user_id="anonymous", tenant_id=tenant_id, username=username, roles=roles or ["admin"])

    def authenticate(self, tenant_id: str, username: str, password: str) -> Identity | None:
        return Identity(user_id="anonymous", tenant_id=tenant_id, username=username, roles=["admin"])

    def authorize(self, identity: Identity, action: str, resource: str = "*") -> bool:
        return True

    def get_user(self, tenant_id: str, username: str) -> Identity | None:
        return Identity(user_id="anonymous", tenant_id=tenant_id, username=username, roles=["admin"])

    def list_users(self, tenant_id: str) -> list[Identity]:
        return []

    def delete_user(self, tenant_id: str, username: str) -> bool:
        return False

    def update_roles(self, tenant_id: str, username: str, roles: list[str]) -> Identity | None:
        return None

    def close(self) -> None:
        pass


# ── OS-level auth providers ───────────────────────────────────


class _OsAuthProvider(AuthProvider):
    """Base class for OS-level authentication providers.

    Subclasses only need to implement ``_os_authenticate`` which verifies
    a username/password pair against the operating system.  All other
    ``AuthProvider`` methods delegate to an inner ``LocalAuthProvider``
    for user management (roles, listing, etc.).  On successful OS auth
    the user is auto-provisioned in the local store if not already present.
    """

    def __init__(self, db_path: str | Path):
        self._local = LocalAuthProvider(db_path)

    @abc.abstractmethod
    def _os_authenticate(self, username: str, password: str) -> bool:
        """Return True if the OS accepts the credentials."""

    def create_user(self, tenant_id: str, username: str, password: str, roles: list[str] | None = None) -> Identity:
        return self._local.create_user(tenant_id, username, password, roles)

    def authenticate(self, tenant_id: str, username: str, password: str) -> Identity | None:
        if not self._os_authenticate(username, password):
            return None
        # Auto-provision the user locally if not yet known
        ident = self._local.get_user(tenant_id, username)
        if ident is None:
            ident = self._local.create_user(tenant_id, username, password, roles=["viewer"])
        return ident

    def authorize(self, identity: Identity, action: str, resource: str = "*") -> bool:
        return self._local.authorize(identity, action, resource)

    def get_user(self, tenant_id: str, username: str) -> Identity | None:
        return self._local.get_user(tenant_id, username)

    def list_users(self, tenant_id: str) -> list[Identity]:
        return self._local.list_users(tenant_id)

    def delete_user(self, tenant_id: str, username: str) -> bool:
        return self._local.delete_user(tenant_id, username)

    def update_roles(self, tenant_id: str, username: str, roles: list[str]) -> Identity | None:
        return self._local.update_roles(tenant_id, username, roles)

    def close(self) -> None:
        self._local.close()


class PamAuthProvider(_OsAuthProvider):
    """Authenticate against PAM (Linux/macOS) using the ``pamela`` library."""

    def _os_authenticate(self, username: str, password: str) -> bool:
        try:
            import pamela  # type: ignore[import-untyped]
        except ImportError:
            logger.error("pamela is not installed — run `pip install pamela`")
            return False
        try:
            pamela.authenticate(username, password)
            return True
        except pamela.PAMError:
            return False


class MacAuthProvider(_OsAuthProvider):
    """Authenticate against macOS OpenDirectory via ``opendirectoryd``."""

    def _os_authenticate(self, username: str, password: str) -> bool:
        if sys.platform != "darwin":
            logger.error("MacAuthProvider is only supported on macOS")
            return False
        try:
            import subprocess  # noqa: S404

            result = subprocess.run(  # noqa: S603
                ["/usr/bin/dscl", "/Local/Default", "-authonly", username, password],
                capture_output=True,
            )
            return result.returncode == 0
        except Exception:
            logger.exception("macOS authentication failed")
            return False


class Win32AuthProvider(_OsAuthProvider):
    """Authenticate against Windows local/domain accounts via ``win32security``."""

    def _os_authenticate(self, username: str, password: str) -> bool:
        if sys.platform != "win32":
            logger.error("Win32AuthProvider is only supported on Windows")
            return False
        try:
            import win32security  # type: ignore[import-untyped]

            handle = win32security.LogonUser(
                username,
                None,  # domain — None means local machine + trusted domains
                password,
                win32security.LOGON32_LOGON_NETWORK,
                win32security.LOGON32_PROVIDER_DEFAULT,
            )
            handle.Close()
            return True
        except ImportError:
            logger.error("pywin32 is not installed — run `pip install pywin32`")
            return False
        except Exception:
            return False


def create_auth_provider(provider: str, db_path: str | Path) -> AuthProvider:
    """Factory: create an AuthProvider by name.

    Supported values for *provider*:
      - ``"none"``  — no authentication (open access)
      - ``"local"`` — SQLite-backed local accounts with PBKDF2 passwords
      - ``"pam"``   — PAM authentication (requires ``pamela``)
      - ``"mac"``   — macOS OpenDirectory authentication
      - ``"win32"`` — Windows local/domain authentication (requires ``pywin32``)
    """
    provider = provider.strip().lower()
    if provider == "none":
        return NoAuthProvider()
    if provider == "local":
        return LocalAuthProvider(db_path)
    if provider == "pam":
        return PamAuthProvider(db_path)
    if provider == "mac":
        return MacAuthProvider(db_path)
    if provider == "win32":
        return Win32AuthProvider(db_path)
    raise ValueError(f"Unknown auth provider: {provider!r} (expected: none, local, pam, mac, win32)")
