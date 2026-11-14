"""GET /v1/me/stream (D50): fan-out to many listeners, heartbeat, replay after a reconnect, a listener that does
not read never holds anything up, ids and kinds only, the same authorization as the other /v1/me routes.

The hub is tested directly (asyncio) and through a real server (uvicorn on a free port, httpx reading the stream):
Starlette's TestClient collects a whole body before it returns, so it cannot read a stream that never ends."""
import asyncio
import json
import queue
import socket
import threading
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn
from kaiku_cloud import stream
from kaiku_cloud.api.main import create_app
from kaiku_cloud.settings import TZ, Settings
from kaiku_contracts import make
from kaiku_contracts.api import StreamAgreed, StreamDay, StreamHello, StreamInvitation
from kaiku_contracts.config import load_config

HOME = "vera"
NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)


def parse(frame: str) -> dict:
    out: dict = {}
    for line in frame.strip().splitlines():
        key, _, value = line.partition(": ")
        out[key] = json.loads(value) if key == "data" else value
    return out


async def take(gen, n: int, timeout: float = 2.0) -> list[dict]:
    return [parse(await asyncio.wait_for(gen.__anext__(), timeout)) for _ in range(n)]


# ---------------------------------------------------------------- the hub alone
async def test_every_listener_of_a_home_gets_the_event_and_no_other_home_does():
    hub = stream.Hub()
    phone, mac, other = (stream.frames(hub, HOME, "iphone", heartbeat_s=5), stream.frames(hub, HOME, "mac", heartbeat_s=5),
                         stream.frames(hub, "someone-else", "iphone", heartbeat_s=5))
    hellos = [(await take(g, 1))[0] for g in (phone, mac, other)]
    assert all(h["event"] == "hello" and "id" not in h for h in hellos)
    assert StreamHello.model_validate(hellos[0]["data"]).resync is False and hellos[0]["retry"] == "2000"
    assert hub.listening(HOME) == ["iphone", "mac"] and hub.listeners() == 3
    ident = hub.publish(HOME, "agreed", {"id": "a1", "kind": "walk", "state": "open"})
    for g in (phone, mac):
        (got,) = await take(g, 1)
        assert got == {"id": ident, "event": "agreed", "data": {"id": "a1", "kind": "walk", "state": "open"}}
    with pytest.raises(asyncio.TimeoutError):
        await take(other, 1, timeout=0.2)  # nothing for another home (and its wait is not a ping yet)
    for g in (phone, mac, other):
        await g.aclose()
    assert hub.listeners() == 0 and hub.listening(HOME) == []


async def test_a_quiet_stream_pings_so_a_dead_connection_is_noticed():
    hub = stream.Hub()
    gen = stream.frames(hub, HOME, heartbeat_s=0.05)
    hello, ping1, ping2 = await take(gen, 3)
    assert hello["data"]["heartbeat_s"] == 0.05
    assert ping1 == ping2 == {"event": "ping", "data": {}}  # no id: a ping never moves Last-Event-ID
    hub.publish(HOME, "day", {"day": "2026-11-14", "types": [], "sources": []})
    assert (await take(gen, 1))[0]["event"] == "day"
    await gen.aclose()


async def test_a_client_that_left_is_dropped_at_the_next_quiet_interval():
    hub = stream.Hub()
    left = {"gone": False}

    async def gone():
        return left["gone"]

    gen = stream.frames(hub, HOME, heartbeat_s=0.05, gone=gone)
    await take(gen, 2)  # hello, ping
    left["gone"] = True
    with pytest.raises(StopAsyncIteration):
        await take(gen, 1)
    assert hub.listeners() == 0


async def test_reconnect_with_last_event_id_gets_exactly_what_was_missed():
    hub = stream.Hub()
    gen = stream.frames(hub, HOME, heartbeat_s=5)
    await take(gen, 1)
    first = hub.publish(HOME, "agreed", {"n": 1})
    assert (await take(gen, 1))[0]["id"] == first
    await gen.aclose()  # the phone goes into a tunnel
    hub.publish("someone-else", "day", {"n": "not theirs"})
    hub.publish(HOME, "agreed", {"n": 2})
    last = hub.publish(HOME, "day", {"n": 3})
    back = stream.frames(hub, HOME, heartbeat_s=5, last_event_id=first)
    hello, two, three = await take(back, 3)
    assert hello["data"] == {"home_id": HOME, "heartbeat_s": 5.0, "last_id": last, "resync": False, "replayed": 2}
    assert [two["data"], three["data"]] == [{"n": 2}, {"n": 3}] and three["id"] == last
    live = hub.publish(HOME, "agreed", {"n": 4})  # and then it simply continues, nothing twice
    assert (await take(back, 1))[0] == {"id": live, "event": "agreed", "data": {"n": 4}}
    await back.aclose()
    # up to date: nothing is replayed
    again = stream.frames(hub, HOME, heartbeat_s=5, last_event_id=live)
    assert (await take(again, 1))[0]["data"]["replayed"] == 0
    await again.aclose()


async def test_an_id_from_another_process_or_older_than_the_buffer_asks_for_a_resync():
    hub = stream.Hub(replay=3)
    ids = [hub.publish(HOME, "day", {"n": n}) for n in range(1, 7)]  # 1, 2 and 3 fall out of the buffer
    for last, resync, replayed in ((ids[0], True, 0), (ids[1], True, 0), (ids[2], False, 3), (ids[4], False, 1),
                                   ("deadbeef-4", True, 0), ("nonsense", True, 0)):
        gen = stream.frames(hub, HOME, heartbeat_s=5, last_event_id=last)
        hello = (await take(gen, 1))[0]["data"]
        assert (hello["resync"], hello["replayed"]) == (resync, replayed), last
        await gen.aclose()
    fresh = stream.frames(hub, HOME, heartbeat_s=5)  # a first connection misses nothing by definition
    assert (await take(fresh, 1))[0]["data"]["resync"] is False
    await fresh.aclose()


async def test_a_listener_that_does_not_read_is_closed_and_never_holds_up_the_publisher():
    hub = stream.Hub(queue=4)
    slow, quick = stream.frames(hub, HOME, "iphone", heartbeat_s=5), stream.frames(hub, HOME, "mac", heartbeat_s=5)
    await take(slow, 1)
    await take(quick, 1)
    started = time.perf_counter()
    for n in range(50):  # the slow one never reads; the quick one keeps up
        hub.publish(HOME, "day", {"n": n})
        assert (await take(quick, 1))[0]["data"] == {"n": n}
    assert time.perf_counter() - started < 1.0
    with pytest.raises(StopAsyncIteration):  # its stream ends instead of growing without bound
        await take(slow, 1)
    assert hub.listening(HOME) == ["mac"]
    back = stream.frames(hub, HOME, "iphone", heartbeat_s=5, last_event_id=f"{hub.epoch}-0")  # and it catches up
    assert (await take(back, 1))[0]["data"]["replayed"] == 50
    await quick.aclose()
    await back.aclose()


async def test_publishing_from_other_threads_reaches_the_listener_in_order():
    hub = stream.Hub()
    gen = stream.frames(hub, HOME, heartbeat_s=5)
    await take(gen, 1)

    def work():
        for n in range(20):
            hub.publish(HOME, "day", {"n": n})

    await asyncio.to_thread(work)  # the API's sync routes run in a threadpool
    got = [f["data"]["n"] for f in await take(gen, 20)]
    assert got == list(range(20))
    await gen.aclose()


async def test_one_more_than_the_limit_closes_the_oldest_listener():
    hub = stream.Hub(max_listeners=2)
    a, b = stream.frames(hub, HOME, heartbeat_s=5), stream.frames(hub, HOME, heartbeat_s=5)
    await take(a, 1)
    await take(b, 1)
    c = stream.frames(hub, HOME, heartbeat_s=5)
    await take(c, 1)
    with pytest.raises(StopAsyncIteration):
        await take(a, 1)
    assert hub.listeners(HOME) == 2
    await b.aclose()
    await c.aclose()


def test_publish_never_raises_and_config_carries_the_limits():
    hub = stream.Hub()
    assert hub.publish(HOME, "day", {"when": datetime.now(UTC)}) is not None  # nobody listening, odd value: fine
    cfg = load_config()["stream"]
    assert {"heartbeat_s", "retry_ms", "replay", "queue", "max_listeners", "hide_types"} <= set(cfg)
    assert (hub.replay, hub.queue, hub.max_listeners) == (cfg["replay"], cfg["queue"], cfg["max_listeners"])
    assert "obs.safety_flag" in cfg["hide_types"]


# ---------------------------------------------------------------- through a real server
class Reader:
    """Reads one SSE connection in a thread, the way an app does."""

    def __init__(self, base: str, home: str = HOME, surface: str | None = "iphone", last: str | None = None,
                 token: str | None = None, last_in_query: str | None = None):
        self.frames: queue.Queue = queue.Queue()
        self.status: int | None = None
        self.content_type = ""
        self._stop = threading.Event()
        headers = {"Accept": "text/event-stream"} | ({"Last-Event-ID": last} if last else {}) | (
            {"Authorization": f"Bearer {token}"} if token else {})
        params = {"home_id": home} | ({"surface": surface} if surface else {}) | (
            {"last_event_id": last_in_query} if last_in_query else {})
        self._thread = threading.Thread(target=self._run, args=(f"{base}/v1/me/stream", params, headers), daemon=True)
        self._thread.start()

    def _run(self, url, params, headers):
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0, read=20.0)) as c, c.stream("GET", url, params=params,
                                                                                   headers=headers) as r:
                self.status, self.content_type = r.status_code, r.headers.get("content-type", "")
                block: list[str] = []
                for line in r.iter_lines():
                    if self._stop.is_set():
                        return
                    if line:
                        block.append(line)
                    elif block:
                        self.frames.put(parse("\n".join(block)))
                        block = []
        except Exception as e:  # the server went away or the test closed us
            self.frames.put({"event": "closed", "data": {"error": type(e).__name__}})
        self.frames.put({"event": "closed", "data": {}})

    def next(self, event: str | None = None, timeout: float = 5.0) -> dict:
        """The next frame (skipping pings unless asked for one)."""
        end = time.time() + timeout
        while True:
            got = self.frames.get(timeout=max(0.01, end - time.time()))
            if got["event"] == (event or got["event"]) and (event == "ping" or got["event"] != "ping"):
                return got

    def close(self):
        self._stop.set()


@pytest.fixture
def served(tmp_path, monkeypatch):
    """The real API on a free local port. Yields (base url, app, open(**kw) -> Reader)."""
    monkeypatch.setitem(load_config()["stream"], "heartbeat_s", 0.2)

    def start(**kw):
        settings = Settings(db_path=str(tmp_path / "served.sqlite"), web_dir=None, home_token=kw.get("home_token"),
                            admin_token=None, clinician_token=kw.get("clinician_token"), home_tokens={},
                            home_id=HOME, demo_mode=kw.get("demo_mode", True), llm="template")
        app = create_app(settings, after_write=kw.get("after_write"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off", timeout_graceful_shutdown=1))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.02)
        assert server.started
        started.append((server, thread))
        return f"http://127.0.0.1:{sock.getsockname()[1]}", app

    started: list = []
    readers: list[Reader] = []

    def reader(base, **kw):
        readers.append(Reader(base, **kw))
        return readers[-1]

    yield start, reader
    for r in readers:
        r.close()
    for server, thread in started:
        server.should_exit = True
        thread.join(5)


def events(base, rows, **kw):
    r = httpx.post(f"{base}/v1/events", json={"events": [e.model_dump(mode="json", exclude_none=True) for e in rows]},
                   timeout=10, **kw)
    assert r.status_code == 200 and not r.json()["rejected"], r.text
    return r


def test_a_check_in_on_the_robot_reaches_the_open_phone_and_mac_within_a_second(served):
    start, reader = served
    base, app = start()
    phone, mac = reader(base, surface="iphone"), reader(base, surface="mac")
    for r in (phone, mac):
        hello = r.next("hello")
        assert r.status == 200 and r.content_type.startswith("text/event-stream")
        assert StreamHello.model_validate(hello["data"]).home_id == HOME
    assert stream.of(app.state.store).listening(HOME) == ["iphone", "mac"]
    sent = time.time()
    events(base, [make("obs.self_report", {"item": "mood", "value": 4, "context": "ritual", "channel": "robot"},
                       source="hub", home_id=HOME, ts=NOW)])
    for r in (phone, mac):
        got = r.next("day", timeout=2)
        day = StreamDay.model_validate(got["data"])
        assert day.types == ["obs.self_report"] and day.sources == ["hub"] and day.day == NOW.astimezone(TZ).date()
        assert set(got["data"]) == {"day", "types", "sources"} and got["id"]  # types and senders, never a value
    assert time.time() - sent < 1.5
    assert phone.next("ping", timeout=2) == {"event": "ping", "data": {}}  # heartbeats over real HTTP


def test_a_yes_to_the_robot_is_on_the_open_phone_and_mac_at_once_and_done_when_it_is_done(served):
    """The whole feature over real HTTP: the robot's hub forwards the tool call; both apps hold their stream open."""
    start, reader = served
    base, app = start()
    get = lambda surface: httpx.get(f"{base}/v1/me/invitation", params={"home_id": HOME, "surface": surface},  # noqa: E731
                                    timeout=10).json()
    phone, mac = reader(base, surface="iphone"), reader(base, surface="mac")
    assert phone.next("hello") and mac.next("hello")
    sid = httpx.post(f"{base}/v1/companion/session", json={"home_id": HOME, "surface": "robot", "intent": "ritual"},
                     timeout=20).json()["session_id"]
    sent = time.time()
    out = httpx.post(f"{base}/v1/companion/tool", timeout=10, json={
        "home_id": HOME, "surface": "robot", "session_id": sid, "name": "agree_activity",
        "args": {"kind": "lantern", "said": "Yes, I'd like that.", "when": "now"}}).json()
    assert out["ok"] and out["result"]["where"] == "your phone and your Mac"
    assert out["result"]["listening"] == ["iphone", "mac"]  # both apps are open right now: it is there this second
    for r in (phone, mac):
        got = StreamAgreed.model_validate(r.next("agreed", timeout=2)["data"])
        assert (got.id, got.kind, got.state, got.surface, got.on) == (out["result"]["id"], "lantern", "open", "robot",
                                                                      ["iphone", "mac"])
    assert time.time() - sent < 1.5
    for surface in ("iphone", "mac"):
        (item,) = get(surface)["agreed"]
        assert item["id"] == out["result"]["id"] and item["state"] == "open" and item["opens_here"]
        assert item["text"] == "With the robot you said yes to Lantern. Ready when you are."
    # the Mac opens it; the phone hears that; the game's own observation finishes it on both
    r = httpx.post(f"{base}/v1/me/agreed/answer", params={"home_id": HOME, "surface": "mac"},
                   json={"id": out["result"]["id"], "answer": "opened"}, timeout=10)
    assert r.status_code == 200 and phone.next("agreed", timeout=2)["data"]["state"] == "started"
    assert mac.next("agreed", timeout=2)["data"]["state"] == "started"
    events(base, [make("obs.play_session", {"game": "lantern", "device": "mac", "duration_s": 75}, source="laptop",
                       home_id=HOME, ts=datetime.now(UTC) + timedelta(seconds=30))])
    for r in (phone, mac):
        assert r.next("agreed", timeout=2)["data"]["state"] == "done"
        assert r.next("day", timeout=2)["data"]["types"] == ["obs.play_session"]
    assert get("iphone")["agreed"][0]["state"] == "done"


def test_an_answered_invitation_is_announced_to_the_other_screens(served):
    start, reader = served
    base, _ = start()
    sid = httpx.post(f"{base}/v1/companion/session", json={"home_id": HOME, "surface": "iphone", "intent": "talk"},
                     timeout=20).json()["session_id"]
    said = "My brother is moving to Oulu next month. I'll miss him."
    httpx.post(f"{base}/v1/companion/tool", timeout=10, json={
        "home_id": HOME, "surface": "iphone", "session_id": sid, "name": "feel",
        "args": {"kind": "sad_news", "heard": {"valence": "low"}, "about": "your brother moving to Oulu", "said": said}})
    item = httpx.get(f"{base}/v1/me/invitation", params={"home_id": HOME, "surface": "iphone"}, timeout=10).json()["invitation"]
    mac = reader(base, surface="mac")
    mac.next("hello")
    assert httpx.post(f"{base}/v1/me/invitation/answer", params={"home_id": HOME},
                      json={"id": item["id"], "answer": "not_now"}, timeout=10).status_code == 200
    got = mac.next("invitation", timeout=2)
    assert StreamInvitation.model_validate(got["data"]).id == item["id"] and "Oulu" not in json.dumps(got)


def test_the_stream_runs_behind_the_commit_hook_the_deployed_app_installs(served):
    """On Modal the app is created with `after_write` (a Volume commit), which adds one more middleware around
    every response. The stream must still arrive frame by frame through it."""
    start, reader = served
    commits = []
    base, _ = start(after_write=lambda: commits.append(1))
    r = reader(base)
    assert r.next("hello")["data"]["home_id"] == HOME
    events(base, [make("obs.self_report", {"item": "mood", "value": 4, "channel": "phone"}, source="phone",
                       home_id=HOME, ts=NOW)])
    assert r.next("day", timeout=2)["data"]["sources"] == ["phone"] and commits
    assert r.next("ping", timeout=2)["event"] == "ping"


def test_reconnect_over_http_replays_what_was_missed_and_a_restart_asks_for_a_resync(served):
    start, reader = served
    base, app = start()
    first = reader(base)
    first.next("hello")
    events(base, [make("obs.outing", {"minutes": 20, "steps": 2000, "method": "steps"}, source="phone", home_id=HOME, ts=NOW)])
    seen = first.next("day")["id"]
    first.close()
    events(base, [make("obs.play_session", {"game": "lantern", "device": "phone", "duration_s": 60}, source="phone",
                       home_id=HOME, ts=NOW)])
    again = reader(base, last=seen)
    hello = again.next("hello")["data"]
    assert (hello["resync"], hello["replayed"]) == (False, 1)
    assert again.next("day")["data"]["types"] == ["obs.play_session"]
    # the same id against another process (a restart): it cannot be continued, so the app reads everything again
    other_base, _ = start()
    restarted = reader(other_base, last=seen)
    assert restarted.next("hello")["data"]["resync"] is True
    # a client that cannot set headers may pass the id in the query
    by_query = reader(base, last_in_query=seen).next("hello")["data"]
    assert (by_query["resync"], by_query["replayed"]) == (False, 1)


def test_a_listener_that_never_reads_does_not_slow_ingest(served):
    start, reader = served
    base, app = start()
    hub = stream.of(app.state.store)
    stuck = socket.create_connection(("127.0.0.1", int(base.rsplit(":", 1)[1])))
    stuck.sendall(f"GET /v1/me/stream?home_id={HOME}&surface=mac HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    deadline = time.time() + 5
    while hub.listeners(HOME) < 1 and time.time() < deadline:
        time.sleep(0.02)
    assert hub.listeners(HOME) == 1  # connected, and from now on it reads nothing at all
    good = reader(base)
    good.next("hello")
    took = []
    for n in range(30):
        row = make("obs.self_report", {"item": "mood", "value": 3, "channel": "phone"}, source="phone", home_id=HOME,
                   ts=NOW - timedelta(seconds=n))
        t0 = time.perf_counter()
        events(base, [row])
        took.append(time.perf_counter() - t0)
        assert good.next("day", timeout=3)["data"]["types"] == ["obs.self_report"]
    assert max(took) < 2.0, took
    stuck.close()


def test_a_closed_connection_is_forgotten(served):
    start, reader = served
    base, app = start()
    hub = stream.of(app.state.store)
    r = reader(base)
    r.next("hello")
    assert hub.listeners(HOME) == 1
    r.close()
    deadline = time.time() + 5
    while hub.listeners(HOME) and time.time() < deadline:
        time.sleep(0.05)
    assert hub.listeners(HOME) == 0


def test_the_stream_needs_the_homes_own_credential(served):
    start, reader = served
    base, _ = start(demo_mode=False, home_token="home-secret", clinician_token="care-secret")
    params = {"home_id": HOME}
    assert httpx.get(f"{base}/v1/me/stream", params=params, timeout=5).status_code == 401
    for token, home in (("care-secret", HOME), ("home-secret", "another-home"), ("wrong", HOME)):
        r = httpx.get(f"{base}/v1/me/stream", params={"home_id": home}, headers={"Authorization": f"Bearer {token}"}, timeout=5)
        assert r.status_code in (401, 403), (token, home)
    mine = reader(base, token="home-secret")
    assert mine.next("hello")["data"]["home_id"] == HOME and mine.status == 200


def test_the_invitation_answer_is_announced_and_event_models_hold_no_words():
    for model in (StreamAgreed, StreamDay, StreamInvitation, StreamHello):
        fields = set(model.model_fields)
        assert not fields & {"text", "line", "said", "topic", "value", "words", "name", "tone", "mood", "score"}, model
    assert StreamInvitation(id="thread:1").state == "answered"
