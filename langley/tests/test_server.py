"""Tests for langley.server (REST API)."""

import json
import sys

import pytest
from starlette.testclient import TestClient

from langley.models import AgentProfile
from langley.server import create_app
from langley.server_state import ServerState


@pytest.fixture()
def state(tmp_path):
    s = ServerState.create_default(data_dir=str(tmp_path / "data"))
    yield s
    s.close()


@pytest.fixture()
def app(state):
    return create_app(state)


@pytest.fixture()
def client(app):
    return TestClient(app)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

class TestHealth:
    def test_healthz(self, client):
        r = client.get("/api/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ------------------------------------------------------------------
# Tenants
# ------------------------------------------------------------------

class TestTenants:
    def test_create_tenant(self, client):
        r = client.post("/api/tenants", json={"name": "acme"})
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "acme"
        assert "id" in data

    def test_create_tenant_no_name(self, client):
        r = client.post("/api/tenants", json={})
        assert r.status_code == 400

    def test_create_duplicate_tenant(self, client):
        client.post("/api/tenants", json={"name": "dup"})
        r = client.post("/api/tenants", json={"name": "dup"})
        assert r.status_code == 409

    def test_get_tenant(self, client):
        r = client.post("/api/tenants", json={"name": "getme"})
        tid = r.json()["id"]
        r = client.get(f"/api/tenants/{tid}")
        assert r.status_code == 200
        assert r.json()["name"] == "getme"

    def test_get_tenant_not_found(self, client):
        r = client.get("/api/tenants/nonexistent")
        assert r.status_code == 404

    def test_list_tenants(self, client):
        client.post("/api/tenants", json={"name": "t1"})
        client.post("/api/tenants", json={"name": "t2"})
        r = client.get("/api/tenants")
        assert r.status_code == 200
        assert len(r.json()) >= 2


# ------------------------------------------------------------------
# Profiles
# ------------------------------------------------------------------

class TestProfiles:
    def test_create_profile(self, client):
        r = client.post("/api/profiles", json={
            "name": "test-bot",
            "tenant_id": "t1",
            "command": ["echo", "hello"],
        })
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "test-bot"
        assert data["version"] == 1

    def test_create_profile_no_name(self, client):
        r = client.post("/api/profiles", json={"tenant_id": "t1"})
        assert r.status_code == 400

    def test_list_profiles(self, client):
        client.post("/api/profiles", json={"name": "p1", "tenant_id": "t1"})
        client.post("/api/profiles", json={"name": "p2", "tenant_id": "t1"})
        r = client.get("/api/profiles")
        assert r.status_code == 200
        assert len(r.json()) >= 2

    def test_list_profiles_by_tenant(self, client):
        client.post("/api/profiles", json={"name": "pa", "tenant_id": "ta"})
        client.post("/api/profiles", json={"name": "pb", "tenant_id": "tb"})
        r = client.get("/api/profiles?tenant_id=ta")
        assert r.status_code == 200
        profiles = r.json()
        assert all(p["tenant_id"] == "ta" for p in profiles)

    def test_get_profile(self, client):
        r = client.post("/api/profiles", json={"name": "getme", "tenant_id": "t1"})
        pid = r.json()["id"]
        r = client.get(f"/api/profiles/{pid}")
        assert r.status_code == 200
        assert r.json()["name"] == "getme"

    def test_get_profile_not_found(self, client):
        r = client.get("/api/profiles/nonexistent")
        assert r.status_code == 404

    def test_delete_profile(self, client):
        r = client.post("/api/profiles", json={"name": "delme", "tenant_id": "t1"})
        pid = r.json()["id"]
        r = client.delete(f"/api/profiles/{pid}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
        # Verify gone
        r = client.get(f"/api/profiles/{pid}")
        assert r.status_code == 404

    def test_delete_profile_not_found(self, client):
        r = client.delete("/api/profiles/nonexistent")
        assert r.status_code == 404


# ------------------------------------------------------------------
# Agents
# ------------------------------------------------------------------

class TestAgents:
    def _create_profile(self, client, name="test-agent", command=None):
        if command is None:
            command = [sys.executable, "-c", "import time; time.sleep(10)"]
        r = client.post("/api/profiles", json={
            "name": name,
            "tenant_id": "t1",
            "command": command,
        })
        return r.json()

    def test_launch_agent_from_profile(self, client):
        profile = self._create_profile(client)
        r = client.post("/api/agents", json={"profile_id": profile["id"]})
        assert r.status_code == 201
        data = r.json()
        assert data["status"] == "running"
        assert data["pid"] is not None
        # Clean up
        client.post(f"/api/agents/{data['agent_id']}/kill")

    def test_launch_agent_inline_profile(self, client):
        r = client.post("/api/agents", json={
            "profile": {
                "name": "inline",
                "tenant_id": "t1",
                "command": [sys.executable, "-c", "import time; time.sleep(10)"],
            }
        })
        assert r.status_code == 201
        agent_id = r.json()["agent_id"]
        client.post(f"/api/agents/{agent_id}/kill")

    def test_launch_agent_nonexistent_profile(self, client):
        r = client.post("/api/agents", json={"profile_id": "no-such"})
        assert r.status_code == 404

    def test_list_agents(self, client):
        profile = self._create_profile(client)
        r1 = client.post("/api/agents", json={"profile_id": profile["id"]})
        r = client.get("/api/agents")
        assert r.status_code == 200
        assert len(r.json()) >= 1
        client.post(f"/api/agents/{r1.json()['agent_id']}/kill")

    def test_get_agent(self, client):
        profile = self._create_profile(client)
        r = client.post("/api/agents", json={"profile_id": profile["id"]})
        aid = r.json()["agent_id"]
        r = client.get(f"/api/agents/{aid}")
        assert r.status_code == 200
        assert r.json()["agent_id"] == aid
        client.post(f"/api/agents/{aid}/kill")

    def test_get_agent_not_found(self, client):
        r = client.get("/api/agents/no-such")
        assert r.status_code == 404

    def test_stop_agent(self, client):
        profile = self._create_profile(client)
        r = client.post("/api/agents", json={"profile_id": profile["id"]})
        aid = r.json()["agent_id"]
        r = client.post(f"/api/agents/{aid}/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "stopping"
        # Clean up
        import time; time.sleep(0.5)
        client.post(f"/api/agents/{aid}/kill")

    def test_kill_agent(self, client):
        profile = self._create_profile(client)
        r = client.post("/api/agents", json={"profile_id": profile["id"]})
        aid = r.json()["agent_id"]
        r = client.post(f"/api/agents/{aid}/kill")
        assert r.status_code == 200
        assert r.json()["status"] == "killed"

    def test_stop_nonexistent(self, client):
        r = client.post("/api/agents/no-such/stop")
        assert r.status_code == 404

    def test_restart_nonexistent(self, client):
        r = client.post("/api/agents/no-such/restart")
        assert r.status_code == 404

    def test_send_message_to_agent(self, client):
        profile = self._create_profile(client)
        r = client.post("/api/agents", json={"profile_id": profile["id"]})
        aid = r.json()["agent_id"]
        r = client.post(f"/api/agents/{aid}/message", json={
            "body": {"hello": "world"},
        })
        assert r.status_code == 201
        assert "message_id" in r.json()
        client.post(f"/api/agents/{aid}/kill")


# ------------------------------------------------------------------
# Messages
# ------------------------------------------------------------------

class TestMessages:
    def test_query_messages(self, client, state):
        from langley.models import Message
        state.transport.send("test-ch", Message(channel="test-ch", body={"n": 1}))
        state.transport.send("test-ch", Message(channel="test-ch", body={"n": 2}))
        r = client.get("/api/messages?channel=test-ch")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_query_messages_no_channel(self, client):
        r = client.get("/api/messages")
        assert r.status_code == 400

    def test_query_messages_with_limit(self, client, state):
        from langley.models import Message
        for i in range(5):
            state.transport.send("lim-ch", Message(channel="lim-ch", body={"n": i}))
        r = client.get("/api/messages?channel=lim-ch&limit=2")
        assert r.status_code == 200
        assert len(r.json()) == 2


# ------------------------------------------------------------------
# Audit
# ------------------------------------------------------------------

class TestAudit:
    def test_query_audit(self, client, state):
        from langley.models import AuditEntry
        state.audit_log.append(AuditEntry(
            tenant_id="t1", agent_id="a1", event_type="test.event",
        ))
        r = client.get("/api/audit?tenant_id=t1")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_query_audit_no_tenant(self, client):
        r = client.get("/api/audit")
        assert r.status_code == 400


# ------------------------------------------------------------------
# Activity feed
# ------------------------------------------------------------------

class TestActivityFeed:
    def test_activity_feed(self, client, state):
        from langley.models import AuditEntry
        state.audit_log.append(AuditEntry(
            tenant_id="t1", agent_id="a1", event_type="agent.launch",
        ))
        state.audit_log.append(AuditEntry(
            tenant_id="t2", agent_id="a2", event_type="agent.stop",
        ))
        r = client.get("/api/activity")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        # Most recent first
        assert data[0]["event_type"] == "agent.stop"

    def test_activity_feed_with_limit(self, client, state):
        from langley.models import AuditEntry
        for i in range(5):
            state.audit_log.append(AuditEntry(
                tenant_id="t1", agent_id=f"a{i}", event_type="test",
            ))
        r = client.get("/api/activity?limit=2")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_activity_feed_empty(self, client):
        r = client.get("/api/activity")
        assert r.status_code == 200
        assert r.json() == []


# ------------------------------------------------------------------
# Providers
# ------------------------------------------------------------------

class TestProviders:
    def test_list_providers(self, client):
        r = client.get("/api/providers")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        assert isinstance(data["providers"], list)
        assert len(data["providers"]) > 0
        # Each provider should have id, name, models
        for p in data["providers"]:
            assert "id" in p
            assert "name" in p
            assert "models" in p
            assert isinstance(p["models"], list)
