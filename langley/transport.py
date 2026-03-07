"""Message transport interface and file-backed implementation."""

import abc
import fcntl
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from langley.models import Message, MessageReceipt


class Subscription:
    """Handle for an active message subscription."""

    def __init__(self, channel: str, unsubscribe_fn: Callable[[], None]):
        self.channel = channel
        self._unsubscribe = unsubscribe_fn
        self._active = True

    @property
    def active(self) -> bool:
        return self._active

    def unsubscribe(self) -> None:
        if self._active:
            self._unsubscribe()
            self._active = False


class MessageTransport(abc.ABC):
    """Interface for sending/receiving messages between agents and the control plane.

    All implementations must provide durable, at-least-once message delivery.
    """

    @abc.abstractmethod
    def send(self, channel: str, message: Message) -> MessageReceipt:
        """Send a message on a channel. Returns a receipt on success."""

    @abc.abstractmethod
    def subscribe(self, channel: str, handler: Callable[[Message], None]) -> Subscription:
        """Subscribe to messages on a channel. The handler is called for each new message."""

    @abc.abstractmethod
    def ack(self, channel: str, message_id: str) -> None:
        """Acknowledge a message as processed."""

    @abc.abstractmethod
    def replay(self, channel: str, from_seq: int = 0) -> Iterator[Message]:
        """Replay messages from a sequence number."""

    @abc.abstractmethod
    def close(self) -> None:
        """Clean up resources."""


def _sanitize_channel(channel: str) -> str:
    """Sanitize a channel name for use as a directory name."""
    return channel.replace("/", "_").replace("..", "_").replace("\x00", "_")


class FileMessageTransport(MessageTransport):
    """File-backed WAL-style message transport.

    Each channel is a directory under base_path containing:
    - messages.jsonl: append-only message log
    - acks.jsonl: acknowledged message IDs
    - sequence: current sequence counter

    Uses fcntl file locking for multi-process write safety.
    """

    def __init__(self, base_path: str | Path, poll_interval: float = 0.1):
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)
        self._poll_interval = poll_interval
        self._lock = threading.Lock()
        self._channel_locks: dict[str, threading.Lock] = {}
        self._closed = False

    def _channel_dir(self, channel: str) -> Path:
        d = self._base / _sanitize_channel(channel)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _get_channel_lock(self, channel: str) -> threading.Lock:
        with self._lock:
            if channel not in self._channel_locks:
                self._channel_locks[channel] = threading.Lock()
            return self._channel_locks[channel]

    def _next_sequence(self, channel_dir: Path) -> int:
        seq_file = channel_dir / "sequence"
        try:
            seq = int(seq_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            seq = 0
        seq += 1
        seq_file.write_text(str(seq))
        return seq

    def send(self, channel: str, message: Message) -> MessageReceipt:
        if self._closed:
            raise RuntimeError("Transport is closed")

        channel_dir = self._channel_dir(channel)
        ch_lock = self._get_channel_lock(channel)

        with ch_lock:
            seq = self._next_sequence(channel_dir)
            message.sequence = seq
            message.channel = channel
            msg_file = channel_dir / "messages.jsonl"
            line = json.dumps(message.to_dict()) + "\n"

            with open(msg_file, "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

        return MessageReceipt(
            message_id=message.id,
            channel=channel,
            sequence=seq,
            timestamp=message.timestamp,
        )

    def subscribe(self, channel: str, handler: Callable[[Message], None]) -> Subscription:
        if self._closed:
            raise RuntimeError("Transport is closed")

        channel_dir = self._channel_dir(channel)
        stop_event = threading.Event()

        def poll_loop() -> None:
            msg_file = channel_dir / "messages.jsonl"
            file_pos = 0
            while not stop_event.is_set():
                try:
                    if msg_file.exists():
                        with open(msg_file, "r") as f:
                            f.seek(file_pos)
                            for line in f:
                                stripped = line.strip()
                                if not stripped:
                                    continue
                                try:
                                    data = json.loads(stripped)
                                    msg = Message.from_dict(data)
                                    handler(msg)
                                except (json.JSONDecodeError, TypeError):
                                    # Partial line or corrupt data; skip
                                    pass
                            file_pos = f.tell()
                except OSError:
                    pass
                stop_event.wait(self._poll_interval)

        thread = threading.Thread(target=poll_loop, daemon=True)
        thread.start()

        def unsub() -> None:
            stop_event.set()

        return Subscription(channel=channel, unsubscribe_fn=unsub)

    def ack(self, channel: str, message_id: str) -> None:
        if self._closed:
            raise RuntimeError("Transport is closed")

        channel_dir = self._channel_dir(channel)
        ack_file = channel_dir / "acks.jsonl"
        line = json.dumps({"message_id": message_id, "timestamp": time.time()}) + "\n"

        with open(ack_file, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def get_acks(self, channel: str) -> set[str]:
        """Return the set of acknowledged message IDs for a channel."""
        channel_dir = self._channel_dir(channel)
        ack_file = channel_dir / "acks.jsonl"
        acks: set[str] = set()
        if not ack_file.exists():
            return acks
        with open(ack_file, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data: dict[str, Any] = json.loads(stripped)
                    acks.add(data["message_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
        return acks

    def replay(self, channel: str, from_seq: int = 0) -> Iterator[Message]:
        channel_dir = self._channel_dir(channel)
        msg_file = channel_dir / "messages.jsonl"
        if not msg_file.exists():
            return

        with open(msg_file, "r") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                    msg = Message.from_dict(data)
                    if msg.sequence > from_seq:
                        yield msg
                except (json.JSONDecodeError, TypeError):
                    pass

    def close(self) -> None:
        self._closed = True
