"""Tests for langley.websocket (WebSocket API)."""

import pytest
from starlette.testclient import TestClient

from langley.models import Message
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


class TestWebSocket:
    def test_ping_pong(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ping"})
            resp = ws.receive_json()
            assert resp["type"] == "pong"

    def test_unknown_frame(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "bogus"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Unknown" in resp["message"]

    def test_invalid_json(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_text("not json at all")
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Invalid JSON" in resp["message"]

    def test_subscribe_and_receive(self, client, state):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "channel": "test-ch"})
            resp = ws.receive_json()
            assert resp["type"] == "subscribed"
            assert resp["channel"] == "test-ch"

            # Send a message on the channel from the server side
            state.transport.send("test-ch", Message(channel="test-ch", body={"n": 42}))

            # Give the polling subscriber time to deliver
            resp = ws.receive_json(mode="text")
            assert resp["type"] == "message"
            assert resp["channel"] == "test-ch"
            assert resp["data"]["body"]["n"] == 42

    def test_subscribe_no_channel(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "channel" in resp["message"]

    def test_unsubscribe(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "channel": "ch1"})
            ws.receive_json()  # subscribed ack

            ws.send_json({"type": "unsubscribe", "channel": "ch1"})
            resp = ws.receive_json()
            assert resp["type"] == "unsubscribed"
            assert resp["channel"] == "ch1"

    def test_unsubscribe_not_subscribed(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "unsubscribe", "channel": "never"})
            resp = ws.receive_json()
            assert resp["type"] == "unsubscribed"

    def test_send_message(self, client, state):
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "type": "send",
                    "channel": "outbox",
                    "body": {"greeting": "hello"},
                }
            )
            resp = ws.receive_json()
            assert resp["type"] == "sent"
            assert "message_id" in resp
            assert "sequence" in resp

        # Verify the message was actually persisted
        msgs = list(state.transport.replay("outbox"))
        assert len(msgs) == 1
        assert msgs[0].body["greeting"] == "hello"

    def test_send_no_channel(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "send", "body": {"x": 1}})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "channel" in resp["message"]

    def test_subscribe_idempotent(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "subscribe", "channel": "ch"})
            resp = ws.receive_json()
            assert resp["type"] == "subscribed"

            # Subscribe again — should still get ack
            ws.send_json({"type": "subscribe", "channel": "ch"})
            resp = ws.receive_json()
            assert resp["type"] == "subscribed"
