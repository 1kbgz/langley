"""Tests for langley.router (MessageRouter)."""

import threading
import time

import pytest

from langley.models import Message, _now
from langley.router import MessageRouter
from langley.transport import FileMessageTransport


@pytest.fixture()
def transport(tmp_path):
    t = FileMessageTransport(tmp_path / "transport", poll_interval=0.05)
    yield t
    t.close()


@pytest.fixture()
def router(transport):
    r = MessageRouter(transport, dedup_window=5.0)
    yield r
    r.close()


# ------------------------------------------------------------------
# Send
# ------------------------------------------------------------------


class TestSend:
    def test_send(self, router, transport):
        msg = Message(channel="ch1", body={"x": 1}, sender="a")
        receipt = router.send("ch1", msg)
        assert receipt.channel == "ch1"
        msgs = list(transport.replay("ch1"))
        assert len(msgs) == 1


# ------------------------------------------------------------------
# Request / Reply
# ------------------------------------------------------------------


class TestRequestReply:
    def test_request_reply(self, router, transport):
        """Full request/reply cycle."""

        def responder():
            """Watch for requests and respond."""
            time.sleep(0.1)
            msgs = list(transport.replay("service"))
            for m in msgs:
                if m.reply_channel:
                    router.reply(m, {"answer": 42}, sender="service")

        t = threading.Thread(target=responder)
        t.start()

        req = Message(channel="service", body={"question": "?"}, sender="client")
        reply = router.request("service", req, timeout=2.0)
        t.join()

        assert reply is not None
        assert reply.body == {"answer": 42}
        assert reply.correlation_id == req.correlation_id

    def test_request_timeout(self, router):
        """Request with no responder should timeout."""
        req = Message(channel="void", body={}, sender="client")
        reply = router.request("void", req, timeout=0.2)
        assert reply is None

    def test_reply_no_reply_channel(self, router):
        """Replying to a message with no reply_channel returns None."""
        msg = Message(channel="ch", body={})
        result = router.reply(msg, {"resp": 1})
        assert result is None


# ------------------------------------------------------------------
# TTL / Expired messages
# ------------------------------------------------------------------


class TestTTL:
    def test_message_not_expired(self):
        msg = Message(channel="ch", body={}, ttl=10.0)
        assert not msg.expired

    def test_message_expired(self):
        msg = Message(channel="ch", body={}, ttl=0.01, timestamp=_now() - 1.0)
        assert msg.expired

    def test_message_no_ttl_never_expires(self):
        msg = Message(channel="ch", body={}, ttl=0, timestamp=_now() - 999999)
        assert not msg.expired

    def test_subscribe_filters_expired(self, router, transport):
        """Expired messages sent to subscribers are routed to dead-letter."""
        received = []
        router.subscribe("ch", lambda m: received.append(m))
        time.sleep(0.1)

        # Send an already-expired message
        expired_msg = Message(
            channel="ch",
            body={"old": True},
            ttl=0.01,
            timestamp=_now() - 1.0,
        )
        transport.send("ch", expired_msg)
        time.sleep(0.2)

        assert len(received) == 0

        # Check dead-letter
        dl = list(router.get_dead_letters())
        assert len(dl) >= 1
        assert dl[0].body["reason"] == "ttl_expired"

    def test_replay_filters_expired(self, router, transport):
        """Replay with filter_expired=True skips expired messages."""
        # Send one fresh and one expired message
        transport.send("ch", Message(channel="ch", body={"fresh": True}))
        transport.send(
            "ch",
            Message(
                channel="ch",
                body={"old": True},
                ttl=0.01,
                timestamp=_now() - 1.0,
            ),
        )

        msgs = list(router.replay("ch", filter_expired=True))
        assert len(msgs) == 1
        assert msgs[0].body.get("fresh") is True

    def test_replay_no_filter(self, router, transport):
        """Replay with filter_expired=False includes expired messages."""
        transport.send("ch", Message(channel="ch", body={"a": 1}))
        transport.send(
            "ch",
            Message(
                channel="ch",
                body={"b": 2},
                ttl=0.01,
                timestamp=_now() - 1.0,
            ),
        )

        msgs = list(router.replay("ch", filter_expired=False))
        assert len(msgs) == 2


# ------------------------------------------------------------------
# Deduplication
# ------------------------------------------------------------------


class TestDedup:
    def test_duplicate_dropped(self, router, transport):
        """Duplicate messages (same id) are dropped by the subscriber."""
        received = []
        router.subscribe("ch", lambda m: received.append(m))
        time.sleep(0.1)

        msg = Message(channel="ch", body={"n": 1}, id="dup-id-1")
        transport.send("ch", msg)
        time.sleep(0.2)

        # Send same message id again
        msg2 = Message(channel="ch", body={"n": 1}, id="dup-id-1")
        transport.send("ch", msg2)
        time.sleep(0.2)

        assert len(received) == 1

    def test_different_ids_not_deduped(self, router, transport):
        received = []
        router.subscribe("ch", lambda m: received.append(m))
        time.sleep(0.1)

        transport.send("ch", Message(channel="ch", body={"n": 1}, id="id-a"))
        transport.send("ch", Message(channel="ch", body={"n": 2}, id="id-b"))
        time.sleep(0.2)

        assert len(received) == 2

    def test_no_dedup_when_disabled(self, router, transport):
        received = []
        router.subscribe("ch", lambda m: received.append(m), deduplicate=False)
        time.sleep(0.1)

        transport.send("ch", Message(channel="ch", body={}, id="same-id"))
        transport.send("ch", Message(channel="ch", body={}, id="same-id"))
        time.sleep(0.2)

        assert len(received) == 2


# ------------------------------------------------------------------
# Dead-letter
# ------------------------------------------------------------------


class TestDeadLetter:
    def test_get_dead_letters_empty(self, router):
        dl = list(router.get_dead_letters())
        assert dl == []


# ------------------------------------------------------------------
# Close
# ------------------------------------------------------------------


class TestClose:
    def test_close_cleans_up(self, transport):
        r = MessageRouter(transport)
        r.subscribe("ch", lambda m: None)
        assert len(r._subscriptions) == 1
        r.close()
        assert len(r._subscriptions) == 0
        assert r._closed is True
