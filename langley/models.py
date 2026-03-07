"""Core data models for langley."""

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def _new_id() -> str:
    """Generate a new unique identifier."""
    return uuid.uuid4().hex


def _now() -> float:
    """Current time as a Unix timestamp."""
    return time.time()


@dataclass
class Message:
    """Canonical message envelope for inter-agent communication."""

    channel: str
    body: dict[str, Any]
    sender: str = ""
    recipient: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=_new_id)
    timestamp: float = field(default_factory=_now)
    sequence: int = 0
    correlation_id: str = ""
    reply_channel: str = ""
    ttl: float = 0.0  # seconds; 0 means no expiry

    @property
    def expired(self) -> bool:
        """Return True if the message has exceeded its TTL."""
        if self.ttl <= 0:
            return False
        return (_now() - self.timestamp) > self.ttl

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MessageReceipt:
    """Returned on successful message send."""

    message_id: str
    channel: str
    sequence: int
    timestamp: float


@dataclass
class AgentProfile:
    """Configuration describing an agent."""

    name: str
    tenant_id: str
    command: list[str] = field(default_factory=list)
    llm_provider: str = ""
    model: str = ""
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    resource_limits: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)
    id: str = field(default_factory=_new_id)
    version: int = 1
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentProfile":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CheckpointData:
    """Agent state checkpoint."""

    agent_id: str
    tenant_id: str
    state: bytes
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=_new_id)
    sequence: int = 0
    machine_id: str = ""
    timestamp: float = field(default_factory=_now)


@dataclass
class AuditEntry:
    """Immutable audit log record."""

    tenant_id: str
    agent_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=_new_id)
    timestamp: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Identity:
    """Authenticated user/service identity."""

    user_id: str
    tenant_id: str
    username: str
    roles: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tenant:
    """Tenant record."""

    name: str
    id: str = field(default_factory=_new_id)
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    resource_quotas: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tenant":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
