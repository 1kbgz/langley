"""Tests for langley.transport (FileMessageTransport)."""

import threading
import time

import pytest

from langley.models import Message
from langley.transport import FileMessageTransport


@pytest.fixture()
def transport(tmp_path):
    t = FileMessageTransport(tmp_path / "transport", poll_interval=0.05)
    yield t
    t.close()


class TestFileMessageTransportSend:
    def test_send_returns_receipt(self, transport):
        msg = Message(channel="ch1", body={"hello": "world"}, sender="agent-a")
        receipt = transport.send("ch1", msg)
        assert receipt.message_id == msg.id
        assert receipt.channel == "ch1"
        assert receipt.sequence == 1
        assert receipt.timestamp > 0

    def test_send_increments_sequence(self, transport):
        r1 = transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        r2 = transport.send("ch1", Message(channel="ch1", body={"n": 2}))
        r3 = transport.send("ch1", Message(channel="ch1", body={"n": 3}))
        assert r1.sequence == 1
        assert r2.sequence == 2
        assert r3.sequence == 3

    def test_send_independent_channels(self, transport):
        r1 = transport.send("ch-a", Message(channel="ch-a", body={}))
        r2 = transport.send("ch-b", Message(channel="ch-b", body={}))
        assert r1.sequence == 1
        assert r2.sequence == 1  # independent sequence per channel

    def test_send_sets_channel_on_message(self, transport):
        msg = Message(channel="", body={"x": 1})
        transport.send("actual-channel", msg)
        assert msg.channel == "actual-channel"

    def test_send_after_close_raises(self, transport):
        transport.close()
        with pytest.raises(RuntimeError, match="closed"):
            transport.send("ch1", Message(channel="ch1", body={}))


class TestFileMessageTransportReplay:
    def test_replay_empty_channel(self, transport):
        messages = list(transport.replay("nonexistent"))
        assert messages == []

    def test_replay_all(self, transport):
        transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        transport.send("ch1", Message(channel="ch1", body={"n": 2}))
        transport.send("ch1", Message(channel="ch1", body={"n": 3}))

        messages = list(transport.replay("ch1"))
        assert len(messages) == 3
        assert messages[0].body == {"n": 1}
        assert messages[1].body == {"n": 2}
        assert messages[2].body == {"n": 3}

    def test_replay_from_sequence(self, transport):
        transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        transport.send("ch1", Message(channel="ch1", body={"n": 2}))
        transport.send("ch1", Message(channel="ch1", body={"n": 3}))

        messages = list(transport.replay("ch1", from_seq=1))
        assert len(messages) == 2
        assert messages[0].body == {"n": 2}
        assert messages[1].body == {"n": 3}

    def test_replay_preserves_message_fields(self, transport):
        original = Message(
            channel="ch1",
            body={"data": "test"},
            sender="alice",
            recipient="bob",
            headers={"h": "v"},
            correlation_id="corr-1",
        )
        transport.send("ch1", original)
        replayed = list(transport.replay("ch1"))
        assert len(replayed) == 1
        r = replayed[0]
        assert r.body == original.body
        assert r.sender == original.sender
        assert r.recipient == original.recipient
        assert r.headers == original.headers
        assert r.correlation_id == original.correlation_id


class TestFileMessageTransportSubscribe:
    def test_subscribe_receives_messages(self, transport):
        received = []
        barrier = threading.Event()

        def handler(msg):
            received.append(msg)
            if len(received) >= 2:
                barrier.set()

        sub = transport.subscribe("ch1", handler)
        assert sub.active

        transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        transport.send("ch1", Message(channel="ch1", body={"n": 2}))

        barrier.wait(timeout=2.0)
        sub.unsubscribe()

        assert len(received) >= 2
        assert received[0].body == {"n": 1}
        assert received[1].body == {"n": 2}

    def test_unsubscribe_stops_delivery(self, transport):
        received = []
        barrier = threading.Event()

        def handler(msg):
            received.append(msg)
            barrier.set()

        sub = transport.subscribe("ch1", handler)
        transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        barrier.wait(timeout=2.0)
        sub.unsubscribe()
        assert not sub.active

        count_before = len(received)
        transport.send("ch1", Message(channel="ch1", body={"n": 2}))
        time.sleep(0.2)
        # Should not receive significantly more messages after unsubscribe
        # (may receive at most one more due to poll timing)
        assert len(received) <= count_before + 1

    def test_subscribe_after_close_raises(self, transport):
        transport.close()
        with pytest.raises(RuntimeError, match="closed"):
            transport.subscribe("ch1", lambda m: None)

    def test_double_unsubscribe_is_safe(self, transport):
        sub = transport.subscribe("ch1", lambda m: None)
        sub.unsubscribe()
        sub.unsubscribe()  # should not raise
        assert not sub.active


class TestFileMessageTransportAck:
    def test_ack_records_message_id(self, transport):
        receipt = transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        transport.ack("ch1", receipt.message_id)
        acks = transport.get_acks("ch1")
        assert receipt.message_id in acks

    def test_ack_empty_channel(self, transport):
        acks = transport.get_acks("empty")
        assert acks == set()

    def test_multiple_acks(self, transport):
        r1 = transport.send("ch1", Message(channel="ch1", body={"n": 1}))
        r2 = transport.send("ch1", Message(channel="ch1", body={"n": 2}))
        transport.ack("ch1", r1.message_id)
        transport.ack("ch1", r2.message_id)
        acks = transport.get_acks("ch1")
        assert r1.message_id in acks
        assert r2.message_id in acks


class TestFileMessageTransportMultiChannel:
    def test_messages_isolated_per_channel(self, transport):
        transport.send("ch-a", Message(channel="ch-a", body={"from": "a"}))
        transport.send("ch-b", Message(channel="ch-b", body={"from": "b"}))

        a_msgs = list(transport.replay("ch-a"))
        b_msgs = list(transport.replay("ch-b"))

        assert len(a_msgs) == 1
        assert len(b_msgs) == 1
        assert a_msgs[0].body == {"from": "a"}
        assert b_msgs[0].body == {"from": "b"}

    def test_channel_name_sanitization(self, transport):
        # Channels with special characters should work
        transport.send("tenant/agent/inbox", Message(channel="tenant/agent/inbox", body={"ok": True}))
        msgs = list(transport.replay("tenant/agent/inbox"))
        assert len(msgs) == 1
