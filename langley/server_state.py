"""Langley server — shared application state (services) for the API layer.

Creates all core services once and shares them across request handlers.
"""

from pathlib import Path

from langley.audit import AuditLog, SqliteAuditLog
from langley.auth import AuthProvider, LocalAuthProvider
from langley.profile import ProfileStore, SqliteProfileStore
from langley.router import MessageRouter
from langley.store import SqliteStateStore, StateStore
from langley.supervisor import AgentProcessManager
from langley.tenant import LocalTenantManager, TenantManager
from langley.transport import FileMessageTransport, MessageTransport


class ServerState:
    """Container for all server-side services.

    In production, callers can inject their own implementations.
    The ``create_default`` factory builds everything from a single data
    directory (SQLite + file transport).
    """

    def __init__(
        self,
        transport: MessageTransport,
        state_store: StateStore,
        audit_log: AuditLog,
        auth_provider: AuthProvider,
        tenant_manager: TenantManager,
        profile_store: ProfileStore,
        router: MessageRouter,
        supervisor: AgentProcessManager,
        static_dir: Path | None = None,
    ):
        self.transport = transport
        self.state_store = state_store
        self.audit_log = audit_log
        self.auth_provider = auth_provider
        self.tenant_manager = tenant_manager
        self.profile_store = profile_store
        self.router = router
        self.supervisor = supervisor
        self.static_dir = static_dir

    @classmethod
    def create_default(cls, data_dir: str = ".langley") -> "ServerState":
        """Build a ServerState with the built-in SQLite/file implementations."""
        base = Path(data_dir)
        base.mkdir(parents=True, exist_ok=True)
        db = str(base / "langley.db")

        transport = FileMessageTransport(base / "transport")
        state_store = SqliteStateStore(db)
        audit_log = SqliteAuditLog(db)
        auth_provider = LocalAuthProvider(db)
        tenant_manager = LocalTenantManager(db)
        profile_store = SqliteProfileStore(db)
        router = MessageRouter(transport)
        supervisor = AgentProcessManager(
            transport=transport,
            state_store=state_store,
            audit_log=audit_log,
        )

        # Resolve static assets directory
        pkg_ext = Path(__file__).parent / "extension"
        static_dir = pkg_ext if pkg_ext.is_dir() else None

        return cls(
            transport=transport,
            state_store=state_store,
            audit_log=audit_log,
            auth_provider=auth_provider,
            tenant_manager=tenant_manager,
            profile_store=profile_store,
            router=router,
            supervisor=supervisor,
            static_dir=static_dir,
        )

    def close(self) -> None:
        self.supervisor.close()
        self.router.close()
        self.transport.close()
