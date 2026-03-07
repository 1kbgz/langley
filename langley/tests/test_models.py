"""Tests for langley.models."""

import time

from langley.models import (
    AgentProfile,
    AuditEntry,
    CheckpointData,
    Identity,
    Message,
    MessageReceipt,
    Tenant,
)


class TestMessage:
    def test_create_with_defaults(self):
        msg = Message(channel="test", body={"hello": "world"})
        assert msg.channel == "test"
        assert msg.body == {"hello": "world"}
        assert msg.sender == ""
        assert msg.recipient == ""
        assert msg.headers == {}
        assert msg.id  # auto-generated
        assert msg.timestamp > 0
        assert msg.sequence == 0
        assert msg.correlation_id == ""
        assert msg.reply_channel == ""
        assert msg.ttl == 0.0
        assert not msg.expired

    def test_create_with_all_fields(self):
        msg = Message(
            channel="ch1",
            body={"data": 42},
            sender="agent-a",
            recipient="agent-b",
            headers={"x-trace": "123"},
            id="msg-001",
            timestamp=time.time(),
            sequence=5,
            correlation_id="corr-1",
            reply_channel="_reply.abc",
            ttl=60.0,
        )
        assert msg.channel == "ch1"
        assert msg.sender == "agent-a"
        assert msg.recipient == "agent-b"
        assert msg.headers["x-trace"] == "123"
        assert msg.id == "msg-001"
        assert msg.sequence == 5
        assert msg.correlation_id == "corr-1"
        assert msg.reply_channel == "_reply.abc"
        assert msg.ttl == 60.0
        assert not msg.expired  # just created

    def test_to_dict(self):
        msg = Message(channel="test", body={"k": "v"}, id="m1", timestamp=100.0)
        d = msg.to_dict()
        assert d["channel"] == "test"
        assert d["body"] == {"k": "v"}
        assert d["id"] == "m1"
        assert d["timestamp"] == 100.0
        assert isinstance(d, dict)

    def test_from_dict(self):
        d = {"channel": "ch", "body": {"x": 1}, "sender": "s1", "id": "m2", "timestamp": 200.0}
        msg = Message.from_dict(d)
        assert msg.channel == "ch"
        assert msg.body == {"x": 1}
        assert msg.sender == "s1"
        assert msg.id == "m2"

    def test_from_dict_ignores_extra_keys(self):
        d = {"channel": "ch", "body": {}, "unknown_field": "ignored"}
        msg = Message.from_dict(d)
        assert msg.channel == "ch"

    def test_roundtrip(self):
        original = Message(
            channel="roundtrip",
            body={"nested": {"a": [1, 2, 3]}},
            sender="alice",
            recipient="bob",
            headers={"h1": "v1"},
            correlation_id="c1",
        )
        restored = Message.from_dict(original.to_dict())
        assert restored.channel == original.channel
        assert restored.body == original.body
        assert restored.sender == original.sender
        assert restored.recipient == original.recipient
        assert restored.headers == original.headers
        assert restored.correlation_id == original.correlation_id
        assert restored.reply_channel == original.reply_channel
        assert restored.ttl == original.ttl

    def test_ttl_expired(self):
        msg = Message(channel="ch", body={}, ttl=0.01, timestamp=time.time() - 1.0)
        assert msg.expired

    def test_ttl_zero_never_expires(self):
        msg = Message(channel="ch", body={}, ttl=0, timestamp=time.time() - 999999)
        assert not msg.expired


class TestMessageReceipt:
    def test_create(self):
        receipt = MessageReceipt(message_id="m1", channel="ch", sequence=1, timestamp=100.0)
        assert receipt.message_id == "m1"
        assert receipt.channel == "ch"
        assert receipt.sequence == 1


class TestAgentProfile:
    def test_create_minimal(self):
        profile = AgentProfile(name="test-agent", tenant_id="t1")
        assert profile.name == "test-agent"
        assert profile.tenant_id == "t1"
        assert profile.command == []
        assert profile.tools == []
        assert profile.id  # auto-generated
        assert profile.version == 1

    def test_create_full(self):
        profile = AgentProfile(
            name="coder",
            tenant_id="t1",
            command=["python", "agent.py"],
            llm_provider="openai",
            model="gpt-4",
            system_prompt="You are a coder.",
            tools=["file_read", "file_write"],
            environment={"OPENAI_API_KEY": "ref:openai-key"},
            resource_limits={"max_memory_mb": 512},
            tags={"team": "backend"},
            secrets=["openai-key"],
        )
        assert profile.llm_provider == "openai"
        assert profile.model == "gpt-4"
        assert len(profile.tools) == 2

    def test_to_dict_from_dict(self):
        original = AgentProfile(name="test", tenant_id="t1", tools=["a", "b"])
        restored = AgentProfile.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.tenant_id == original.tenant_id
        assert restored.tools == original.tools


class TestCheckpointData:
    def test_create(self):
        cp = CheckpointData(
            agent_id="a1",
            tenant_id="t1",
            state=b"binary-state-data",
            metadata={"step": 42},
            sequence=10,
            machine_id="machine-1",
        )
        assert cp.agent_id == "a1"
        assert cp.state == b"binary-state-data"
        assert cp.metadata == {"step": 42}
        assert cp.sequence == 10
        assert cp.machine_id == "machine-1"

    def test_defaults(self):
        cp = CheckpointData(agent_id="a1", tenant_id="t1", state=b"")
        assert cp.metadata == {}
        assert cp.sequence == 0
        assert cp.machine_id == ""
        assert cp.id  # auto-generated
        assert cp.timestamp > 0


class TestAuditEntry:
    def test_create(self):
        entry = AuditEntry(
            tenant_id="t1",
            agent_id="a1",
            event_type="agent.started",
            payload={"profile": "coder"},
        )
        assert entry.tenant_id == "t1"
        assert entry.event_type == "agent.started"
        assert entry.id
        assert entry.timestamp > 0

    def test_roundtrip(self):
        original = AuditEntry(
            tenant_id="t1",
            agent_id="a1",
            event_type="test",
            payload={"key": "value"},
        )
        restored = AuditEntry.from_dict(original.to_dict())
        assert restored.tenant_id == original.tenant_id
        assert restored.agent_id == original.agent_id
        assert restored.event_type == original.event_type
        assert restored.payload == original.payload


class TestIdentity:
    def test_create(self):
        ident = Identity(user_id="u1", tenant_id="t1", username="alice", roles=["admin"])
        assert ident.user_id == "u1"
        assert ident.username == "alice"
        assert ident.roles == ["admin"]

    def test_defaults(self):
        ident = Identity(user_id="u1", tenant_id="t1", username="bob")
        assert ident.roles == []
        assert ident.metadata == {}


class TestTenant:
    def test_create_minimal(self):
        t = Tenant(name="acme")
        assert t.name == "acme"
        assert t.active is True
        assert t.id
        assert t.created_at > 0

    def test_create_full(self):
        t = Tenant(
            name="acme",
            id="t-123",
            active=False,
            metadata={"plan": "enterprise"},
            resource_quotas={"max_agents": 100},
        )
        assert t.id == "t-123"
        assert t.active is False
        assert t.metadata["plan"] == "enterprise"
        assert t.resource_quotas["max_agents"] == 100

    def test_roundtrip(self):
        original = Tenant(name="corp", metadata={"k": "v"}, resource_quotas={"q": 1})
        restored = Tenant.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.metadata == original.metadata
        assert restored.resource_quotas == original.resource_quotas

    def test_unique_ids(self):
        t1 = Tenant(name="a")
        t2 = Tenant(name="b")
        assert t1.id != t2.id

    def test_timestamp_ordering(self):
        t1 = Tenant(name="first")
        time.sleep(0.01)
        t2 = Tenant(name="second")
        assert t2.created_at >= t1.created_at
