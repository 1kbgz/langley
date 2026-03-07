"""Tests for langley.agent (AgentSDK)."""

import os
import threading
import time

import pytest

from langley.agent import AgentContext, AgentSDK
from langley.models import Message
from langley.transport import FileMessageTransport


@pytest.fixture()
def transport(tmp_path):
    t = FileMessageTransport(tmp_path / "transport", poll_interval=0.05)
    yield t
    t.close()


@pytest.fixture()
def context():
    return AgentContext(
        agent_id="agent-1",
        tenant_id="t1",
        profile_id="p1",
        profile_name="test-agent",
    )


@pytest.fixture()
def sdk(context, transport):
    s = AgentSDK(context=context, transport=transport)
    yield s
    s.close()


class TestAgentContext:
    def test_fields(self, context):
        assert context.agent_id == "agent-1"
        assert context.tenant_id == "t1"
        assert context.profile_id == "p1"
        assert context.profile_name == "test-agent"
        assert context.checkpoint is None


class TestFromEnv:
    def test_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LANGLEY_AGENT_ID", "a1")
        monkeypatch.setenv("LANGLEY_TENANT_ID", "t1")
        monkeypatch.setenv("LANGLEY_PROFILE_ID", "p1")
        monkeypatch.setenv("LANGLEY_PROFILE_NAME", "my-agent")
        sdk = AgentSDK.from_env(transport_dir=str(tmp_path / "tr"))
        try:
            assert sdk.agent_id == "a1"
            assert sdk.tenant_id == "t1"
            assert sdk.context.profile_id == "p1"
        finally:
            sdk.close()

    def test_from_env_missing_agent_id(self, monkeypatch):
        monkeypatch.delenv("LANGLEY_AGENT_ID", raising=False)
        with pytest.raises(RuntimeError, match="LANGLEY_AGENT_ID"):
            AgentSDK.from_env()


class TestSend:
    def test_send_message(self, sdk, transport):
        sdk.send("output", {"result": 42})
        msgs = list(transport.replay("output"))
        assert len(msgs) == 1
        assert msgs[0].body == {"result": 42}
        assert msgs[0].sender == "agent-1"

    def test_send_with_headers(self, sdk, transport):
        sdk.send("output", {"x": 1}, headers={"trace-id": "abc"})
        msgs = list(transport.replay("output"))
        assert msgs[0].headers == {"trace-id": "abc"}


class TestSendTo:
    def test_send_to_agent(self, sdk, transport):
        sdk.send_to("agent-2", {"hello": "world"})
        msgs = list(transport.replay("agent.agent-2.inbox"))
        assert len(msgs) == 1
        assert msgs[0].recipient == "agent-2"
        assert msgs[0].body == {"hello": "world"}


class TestReceive:
    def test_receive_from_inbox(self, sdk, transport):
        # another agent sends to this agent's inbox
        transport.send(
            "agent.agent-1.inbox",
            Message(channel="agent.agent-1.inbox", body={"hello": 1}, sender="other"),
        )
        msgs = list(sdk.receive())
        assert len(msgs) == 1
        assert msgs[0].body == {"hello": 1}

    def test_receive_from_specific_channel(self, sdk, transport):
        transport.send("custom-ch", Message(channel="custom-ch", body={"n": 1}))
        msgs = list(sdk.receive("custom-ch"))
        assert len(msgs) == 1


class TestSubscribe:
    def test_subscribe(self, sdk, transport):
        received = []
        sdk.subscribe("events", lambda msg: received.append(msg))
        time.sleep(0.1)  # let subscriber thread start
        transport.send("events", Message(channel="events", body={"event": 1}))
        time.sleep(0.2)  # let poll pick it up
        assert len(received) >= 1
        assert received[0].body == {"event": 1}


class TestReportStatus:
    def test_report_status(self, sdk, transport):
        sdk.report_status({"progress": 0.5, "task": "processing"})
        msgs = list(transport.replay("agent.agent-1.status"))
        assert len(msgs) == 1
        assert msgs[0].body["type"] == "status_update"
        assert msgs[0].body["status"]["progress"] == 0.5


class TestLog:
    def test_log(self, sdk, transport):
        sdk.log("info", "Hello world", extra_key="val")
        msgs = list(transport.replay("agent.agent-1.logs"))
        assert len(msgs) == 1
        assert msgs[0].body["level"] == "info"
        assert msgs[0].body["message"] == "Hello world"
        assert msgs[0].body["extra_key"] == "val"


class TestRequestApproval:
    def test_request_approval(self, sdk, transport):
        req_id = sdk.request_approval("Deploy to prod?", metadata={"env": "prod"})
        assert isinstance(req_id, str)
        assert len(req_id) > 0
        msgs = list(transport.replay("agent.agent-1.approvals"))
        assert len(msgs) == 1
        assert msgs[0].body["type"] == "approval_request"
        assert msgs[0].body["request_id"] == req_id
        assert msgs[0].body["description"] == "Deploy to prod?"


class TestHeartbeat:
    def test_emit_heartbeat(self, sdk, transport):
        sdk.emit_heartbeat()
        msgs = list(transport.replay("agent.heartbeats"))
        assert len(msgs) == 1
        assert msgs[0].body["type"] == "heartbeat"
        assert msgs[0].body["agent_id"] == "agent-1"

    def test_start_stop_heartbeat(self, sdk, transport):
        sdk.start_heartbeat(interval=0.05)
        time.sleep(0.2)
        sdk.stop_heartbeat()
        msgs = list(transport.replay("agent.heartbeats"))
        assert len(msgs) >= 2  # at least a few heartbeats

    def test_start_heartbeat_idempotent(self, sdk):
        sdk.start_heartbeat(interval=0.1)
        t = sdk._heartbeat_thread
        sdk.start_heartbeat(interval=0.1)
        assert sdk._heartbeat_thread is t
        sdk.stop_heartbeat()


class TestClose:
    def test_close_cleans_up_subscriptions(self, context, transport):
        sdk = AgentSDK(context=context, transport=transport)
        sdk.subscribe("ch", lambda m: None)
        assert len(sdk._subscriptions) == 1
        sdk.close()
        assert len(sdk._subscriptions) == 0
