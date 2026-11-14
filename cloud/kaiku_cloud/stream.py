"""GET /v1/me/stream — what changed for one home, pushed to every screen that is open (Server-Sent Events, D50).

The apps keep one stream open while they run. The cloud sends a small event whenever something a screen should
react to changes for that home: an agreed activity appeared or changed (`agreed`), new observations were stored
(`day`), the daily invitation was answered (`invitation`). Events carry ids and kinds only: never words from a
conversation, never a value, never anything about how the person is. The screen reads the sentence it needs with
the ordinary routes (`GET /v1/me/invitation`, `GET /v1/me`).

In process on purpose: the cloud runs as exactly one warm container (one SQLite writer), so the request that
changes something and every open stream are in the same Python process. `Hub.publish` may be called from any
thread (FastAPI runs the sync routes in a threadpool); it never waits for a listener and never raises.

    hello       first frame of a connection, no id: heartbeat, the newest id, `resync` when events may be missing
    <event>     `id: <epoch>-<n>`: n counts up while this process lives, epoch changes when it restarts
    ping        no id, whenever nothing else was sent for `[stream].heartbeat_s`

Reconnect with `Last-Event-ID`: events after it are sent again from a per-home buffer (`[stream].replay`). An id
from another process, or one older than the buffer, cannot be continued: `hello.resync` is true and the screen
reads everything again. A listener that does not read (queue of `[stream].queue` full) is closed, never waited
for; it reconnects and continues from its last id. At most `[stream].max_listeners` per home: the oldest goes.

Across several containers this would need a shared channel (Redis pub/sub or Postgres LISTEN/NOTIFY) with the
replay buffer in the same store (a Redis stream, or an `events_out` table with a serial id), so an id means the
same thing on every container. Nothing else here would change.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import weakref
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from kaiku_contracts.config import load_config
from kaiku_contracts.jlog import get_logger

log = get_logger("cloud.stream")
PING = "event: ping\ndata: {}\n\n"
HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
_CLOSE = object()  # put on a listener's queue to end its stream


def cfg() -> dict[str, Any]:
    return load_config().get("stream", {})


@dataclass(frozen=True)
class Event:
    seq: int
    name: str
    data: str  # JSON text

    def frame(self, epoch: str) -> str:
        return f"id: {epoch}-{self.seq}\nevent: {self.name}\ndata: {self.data}\n\n"


@dataclass(eq=False)
class Listener:
    home_id: str
    surface: str | None
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    backlog: list[Event] = field(default_factory=list)  # events to send again after a reconnect
    resync: bool = False
    lost: bool = False  # it did not keep up and was closed

    def offer(self, event: Any) -> None:
        """Runs on the listener's own loop. A full queue means nobody is reading: drop what is waiting and end the
        stream, so the client reconnects and continues from the last id it really received."""
        if self.lost:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.lost = True
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(_CLOSE)


class Hub:
    """Fan-out and replay for one API process."""

    def __init__(self, replay: int | None = None, queue: int | None = None, max_listeners: int | None = None):
        c = cfg()
        self.epoch = format(time.time_ns() // 1_000_000, "x")  # a restart makes every old id unknown
        self.replay = int(replay if replay is not None else c.get("replay", 200))
        self.queue = int(queue if queue is not None else c.get("queue", 64))
        self.max_listeners = int(max_listeners if max_listeners is not None else c.get("max_listeners", 12))
        self._lock = threading.Lock()
        self._seq = 0
        self._buffers: dict[str, deque[Event]] = {}
        self._evicted: dict[str, int] = {}  # per home: seq of the newest event that fell out of the buffer
        self._listeners: dict[str, list[Listener]] = {}

    # ------------------------------------------------------------------ publish (any thread)
    def publish(self, home_id: str, name: str, data: dict[str, Any]) -> str | None:
        """Store the event for replay and hand it to every open stream of that home. Returns its id.
        Never blocks and never raises: a stream is a convenience, the change it reports is already saved."""
        try:
            text = json.dumps(data, separators=(",", ":"), default=str)
            with self._lock:
                self._seq += 1
                event = Event(self._seq, name, text)
                buf = self._buffers.setdefault(home_id, deque())
                buf.append(event)
                while len(buf) > self.replay:
                    self._evicted[home_id] = buf.popleft().seq
                targets = list(self._listeners.get(home_id, ()))
            for listener in targets:
                self._hand(listener, event)
            log.info("stream_event", name, home=home_id, listeners=len(targets))  # the name only, never the data
            return f"{self.epoch}-{event.seq}"
        except Exception as e:  # pragma: no cover - a broken stream must never fail the write that caused it
            log.warning("stream_publish_failed", type(e).__name__, home=home_id)
            return None

    def _hand(self, listener: Listener, event: Any) -> None:
        try:
            listener.loop.call_soon_threadsafe(listener.offer, event)
        except RuntimeError:  # its event loop is gone
            self.unsubscribe(listener)

    # ------------------------------------------------------------------ listeners (their own loop)
    def subscribe(self, home_id: str, surface: str | None = None, last_event_id: str | None = None) -> Listener:
        """Register a listener and, atomically with that, work out what it missed since `last_event_id`."""
        listener = Listener(home_id, surface, asyncio.get_running_loop(), asyncio.Queue(maxsize=self.queue))
        with self._lock:
            epoch, _, seq = (last_event_id or "").strip().rpartition("-")
            if last_event_id:
                if epoch == self.epoch and seq.isdigit() and int(seq) >= self._evicted.get(home_id, 0):
                    listener.backlog = [e for e in self._buffers.get(home_id, ()) if e.seq > int(seq)]
                else:
                    listener.resync = True  # another process, or further back than the buffer reaches
            mine = self._listeners.setdefault(home_id, [])
            mine.append(listener)
            extra = mine[:-self.max_listeners] if len(mine) > self.max_listeners else []
            del mine[:len(extra)]
        for old in extra:  # most likely a connection nobody reads any more
            self._hand(old, _CLOSE)
        return listener

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            mine = self._listeners.get(listener.home_id, [])
            if listener in mine:
                mine.remove(listener)
            if not mine:
                self._listeners.pop(listener.home_id, None)

    def listening(self, home_id: str) -> list[str]:
        """Surfaces whose stream is open for this home right now (those that said which they are)."""
        with self._lock:
            return sorted({x.surface for x in self._listeners.get(home_id, ()) if x.surface})

    def listeners(self, home_id: str | None = None) -> int:
        with self._lock:
            return sum(len(v) for k, v in self._listeners.items() if home_id in (None, k))

    def last_id(self, home_id: str) -> str | None:
        with self._lock:
            buf = self._buffers.get(home_id)
            return f"{self.epoch}-{buf[-1].seq}" if buf else None


_hubs: weakref.WeakKeyDictionary[Any, Hub] = weakref.WeakKeyDictionary()
_hubs_lock = threading.Lock()


def of(store: Any) -> Hub:
    """The hub that belongs to this API process's store (one per app, so tests do not share listeners)."""
    with _hubs_lock:
        hub = _hubs.get(store)
        if hub is None:
            hub = _hubs[store] = Hub()
        return hub


def publish(store: Any, home_id: str, name: str, data: dict[str, Any]) -> str | None:
    return of(store).publish(home_id, name, data)


def day_changed(store: Any, home_id: str, events: list[dict[str, Any]]) -> str | None:
    """New observations of one home were stored: tell its screens the day changed. Types and senders only; a type
    in `[stream].hide_types` is never named (the event still goes out, so the screens read again)."""
    if not events:
        return None
    from .analytics.metrics import local_date

    hidden = set(cfg().get("hide_types", []))
    return publish(store, home_id, "day", {
        "day": max(local_date(e["ts"]) for e in events).isoformat(),
        "types": sorted({e["type"] for e in events} - hidden),
        "sources": sorted({e["source"] for e in events})})


async def frames(hub: Hub, home_id: str, surface: str | None = None, last_event_id: str | None = None,
                 heartbeat_s: float | None = None,
                 gone: Callable[[], Awaitable[bool]] | None = None) -> AsyncIterator[str]:
    """The SSE body of one connection: hello, what was missed, then events as they happen, a ping when quiet.
    `gone`: asked at every quiet interval, so a connection whose client left is dropped even when the server
    below does not report the failed write (the request's `is_disconnected`)."""
    beat = float(heartbeat_s if heartbeat_s is not None else cfg().get("heartbeat_s", 15))
    listener = hub.subscribe(home_id, surface, last_event_id)
    try:
        hello = {"home_id": home_id, "heartbeat_s": beat, "last_id": hub.last_id(home_id),
                 "resync": listener.resync, "replayed": len(listener.backlog)}
        yield f"retry: {int(cfg().get('retry_ms', 2000))}\nevent: hello\ndata: {json.dumps(hello)}\n\n"
        for event in listener.backlog:
            yield event.frame(hub.epoch)
        listener.backlog = []
        while True:
            try:
                event = await asyncio.wait_for(listener.queue.get(), timeout=beat)
            except TimeoutError:
                if gone is not None and await gone():
                    return
                yield PING
                continue
            if event is _CLOSE:
                return
            yield event.frame(hub.epoch)
    finally:
        hub.unsubscribe(listener)
