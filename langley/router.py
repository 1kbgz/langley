"""Higher-level messaging patterns built on top of MessageTransport.

Provides request/reply, dead-letter handling, TTL filtering, and
duplicate detection.
"""

import threading
import time
from typing import Any, Callable, Iterator

from langley.models import Message, MessageReceipt, _new_id, _now
from langley.transport import MessageTransport, Subscription


DEAD_LETTER_CHANNEL = "_dead_letter"


class MessageRouter:
    """Adds request/reply, TTL, dedup, and dead-letter capabilities
    on top of a raw ``MessageTransport``.

    Usage::

        router = MessageRouter(transport)
        # fire-and-forget
        router.send("channel", Message(...))
        # request/reply
        reply = router.request("channel", Message(...), timeout=5.0)
        # subscribe with automatic TTL filtering + dedup
        router.subscribe("channel", handler)
    """

    def __init__(
        self,
        transport: MessageTransport,
        dedup_window: float = 300.0,
    ):
        self._transport = transport
        self._dedup_window = dedup_window

        # dedup tracking: message_id -> timestamp
        self._seen: dict[str, float] = {}
        self._seen_lock = threading.Lock()

        # pending request/reply futures: correlation_id -> Event + result slot
        self._pending: dict[str, tuple[threading.Event, list[Message]]] = {}
        self._pending_lock = threading.Lock()

        self._subscriptions: list[Subscription] = []
        self._closed = False

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send(self, channel: str, message: Message) -> MessageReceipt:
        """Send a message, identical to the underlying transport."""
        return self._transport.send(channel, message)

    # ------------------------------------------------------------------
    # Request / Reply
    # ------------------------------------------------------------------

    def request(
        self,
        channel: str,
        message: Message,
        timeout: float = 30.0,
    ) -> Message | None:
        """Send a request and block until a reply arrives or *timeout* expires.

        The caller's message gets a ``reply_channel`` set automatically.
        The responder should send their reply to that channel with the same
        ``correlation_id``.

        Returns the reply ``Message``, or ``None`` on timeout.
        """
        corr_id = message.correlation_id or _new_id()
        message.correlation_id = corr_id
        reply_ch = f"_reply.{corr_id}"
        message.reply_channel = reply_ch

        event = threading.Event()
        slot: list[Message] = []

        with self._pending_lock:
            self._pending[corr_id] = (event, slot)

        # Subscribe to the reply channel
        def _on_reply(msg: Message) -> None:
            if msg.correlation_id == corr_id:
                slot.append(msg)
                event.set()

        sub = self._transport.subscribe(reply_ch, _on_reply)

        try:
            self._transport.send(channel, message)
            event.wait(timeout=timeout)
        finally:
            sub.unsubscribe()
            with self._pending_lock:
                self._pending.pop(corr_id, None)

        return slot[0] if slot else None

    def reply(self, original: Message, body: dict[str, Any], sender: str = "") -> MessageReceipt | None:
        """Send a reply to a request message.

        Uses the ``reply_channel`` and ``correlation_id`` from the original.
        Returns None if the original has no ``reply_channel``.
        """
        if not original.reply_channel:
            return None
        reply_msg = Message(
            channel=original.reply_channel,
            body=body,
            sender=sender,
            recipient=original.sender,
            correlation_id=original.correlation_id,
        )
        return self._transport.send(original.reply_channel, reply_msg)

    # ------------------------------------------------------------------
    # Subscribe (with TTL filtering + dedup)
    # ------------------------------------------------------------------

    def subscribe(
        self,
        channel: str,
        handler: Callable[[Message], None],
        filter_expired: bool = True,
        deduplicate: bool = True,
    ) -> Subscription:
        """Subscribe to a channel with optional TTL filtering and dedup.

        Expired messages are automatically routed to the dead-letter channel.
        Duplicate messages (same ``id`` seen within ``dedup_window``) are dropped.
        """

        def _wrapped(msg: Message) -> None:
            # TTL check
            if filter_expired and msg.expired:
                self._dead_letter(msg, reason="ttl_expired")
                return

            # Dedup
            if deduplicate and self._is_duplicate(msg.id):
                return

            handler(msg)

        sub = self._transport.subscribe(channel, _wrapped)
        self._subscriptions.append(sub)
        return sub

    # ------------------------------------------------------------------
    # Replay (with TTL filtering)
    # ------------------------------------------------------------------

    def replay(
        self,
        channel: str,
        from_seq: int = 0,
        filter_expired: bool = True,
    ) -> Iterator[Message]:
        """Replay messages, optionally skipping expired ones."""
        for msg in self._transport.replay(channel, from_seq=from_seq):
            if filter_expired and msg.expired:
                continue
            yield msg

    # ------------------------------------------------------------------
    # Dead-letter
    # ------------------------------------------------------------------

    def _dead_letter(self, message: Message, reason: str = "") -> None:
        """Route a message to the dead-letter channel."""
        dl_msg = Message(
            channel=DEAD_LETTER_CHANNEL,
            body={
                "original_channel": message.channel,
                "original_id": message.id,
                "original_body": message.body,
                "reason": reason,
            },
            sender="langley.router",
            headers={"original_sender": message.sender},
        )
        try:
            self._transport.send(DEAD_LETTER_CHANNEL, dl_msg)
        except Exception:
            pass  # best-effort

    def get_dead_letters(self, from_seq: int = 0) -> Iterator[Message]:
        """Retrieve messages from the dead-letter channel."""
        return self._transport.replay(DEAD_LETTER_CHANNEL, from_seq=from_seq)

    # ------------------------------------------------------------------
    # Dedup
    # ------------------------------------------------------------------

    def _is_duplicate(self, message_id: str) -> bool:
        """Check if we've seen this message recently. Records it if new."""
        now = _now()
        with self._seen_lock:
            # Prune old entries
            cutoff = now - self._dedup_window
            expired_keys = [k for k, ts in self._seen.items() if ts < cutoff]
            for k in expired_keys:
                del self._seen[k]

            if message_id in self._seen:
                return True
            self._seen[message_id] = now
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Unsubscribe all managed subscriptions."""
        self._closed = True
        for sub in self._subscriptions:
            sub.unsubscribe()
        self._subscriptions.clear()
        with self._seen_lock:
            self._seen.clear()
        with self._pending_lock:
            # Wake any blocked requests
            for event, _ in self._pending.values():
                event.set()
            self._pending.clear()
