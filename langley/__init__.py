__version__ = "0.1.2"

from langley.agent import AgentContext, AgentSDK
from langley.audit import AuditLog, SqliteAuditLog
from langley.auth import AuthProvider, LocalAuthProvider, MacAuthProvider, NoAuthProvider, PamAuthProvider, Win32AuthProvider, create_auth_provider
from langley.config import load_config
from langley.models import (
    AgentProfile,
    AuditEntry,
    CheckpointData,
    Identity,
    Message,
    MessageReceipt,
    Tenant,
)
from langley.profile import (
    ProfileStore,
    SqliteProfileStore,
    load_profile_from_file,
    load_profile_from_string,
    merge_profiles,
)
from langley.router import DEAD_LETTER_CHANNEL, MessageRouter
from langley.server import create_app
from langley.server_state import ServerState
from langley.store import SqliteStateStore, StateStore
from langley.supervisor import (
    AgentInfo,
    AgentProcessManager,
    AgentStatus,
    RestartPolicy,
)
from langley.tenant import LocalTenantManager, TenantManager
from langley.transport import FileMessageTransport, MessageTransport, Subscription

__all__ = [
    "__version__",
    # Models
    "AgentProfile",
    "AuditEntry",
    "CheckpointData",
    "Identity",
    "Message",
    "MessageReceipt",
    "Tenant",
    # Interfaces
    "AuditLog",
    "AuthProvider",
    "MessageTransport",
    "ProfileStore",
    "StateStore",
    "Subscription",
    "TenantManager",
    # Agent lifecycle
    "AgentContext",
    "AgentInfo",
    "AgentProcessManager",
    "AgentSDK",
    "AgentStatus",
    "RestartPolicy",
    # Profile management
    "SqliteProfileStore",
    "load_profile_from_file",
    "load_profile_from_string",
    "merge_profiles",
    # Router / messaging patterns
    "DEAD_LETTER_CHANNEL",
    "MessageRouter",
    # Server / API
    "ServerState",
    "create_app",
    # Built-in implementations
    "FileMessageTransport",
    "LocalAuthProvider",
    "LocalTenantManager",
    "MacAuthProvider",
    "NoAuthProvider",
    "PamAuthProvider",
    "SqliteAuditLog",
    "SqliteStateStore",
    "Win32AuthProvider",
    "create_auth_provider",
    "load_config",
]
