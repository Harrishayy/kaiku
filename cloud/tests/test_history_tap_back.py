"""Tap it back in the person's History (D48 + D51): the robot's rhythm game as numbers by day, read by no rule."""
import re
from datetime import UTC, date, datetime, time, timedelta

from kaiku_cloud import history, service
from kaiku_cloud.jobs import single_person
from kaiku_cloud.settings import TZ
from kaiku_cloud.store.db import Store
from kaiku_contracts import make

END = date(2026, 11, 13)
TODAY = END + timedelta(days=1)
NOW = datetime.combine(TODAY, time(20, 0), TZ)
# What the person is never shown (D48; the same lists as test_history.py).
FORBIDDEN_KEY = re.compile(r"state|verdict|consensus|(^|_)z(_|$)|zscore|flag|weight|worse|better|direction|review|"
                           r"finding|safety|phq|item9|confidence|agreement|drift|baseline|threshold|score|risk", re.I)
FORBIDDEN_WORD = re.compile(r"needs.{0,3}call|worth a check|\bstable\b|insufficient|worse|better|drift|improv|declin|"
                            r"relapse|diagnos|z-score|flag|phq|questionnaire answer|safety|consensus|verdict|weight|"
                            r"baseline|\bscore|review|risk|worr", re.I)


def walk(node, key=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k, v
            yield from walk(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v, key)
    else:
        yield key, node


def assert_numbers_only(body: dict) -> None:
    for key, value in walk(body):
        assert not FORBIDDEN_KEY.search(key), key
        if isinstance(value, str) and key not in ("device", "devices", "id", "home_id"):
            assert not FORBIDDEN_WORD.search(value), (key, value)


def measures(h) -> dict:
    return {m["key"]: m for g in h.model_dump(mode="json")["groups"] for m in g["measures"]}


def at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), TZ).astimezone(UTC)


def put(store: Store, kind: str, payload: dict, ts: datetime, source: str = "phone", home: str = "h",
        quality: float | None = None) -> str:
    row = make(kind, payload, source=source, home_id=home, quality=quality, ts=ts).model_dump(mode="json")
    store.insert_events([row])
    return row["id"]


def test_tap_it_back_is_listed_with_numbers_only_and_never_as_drumming():
    """The robot's rhythm game is the person's own to look at: songs on the beat and timing by day, the numbers of
    each session. No band word, nothing about a state, and it is not a drum session (her own tempo)."""
    from kaiku_contracts import EXAMPLES

    store = Store(":memory:")
    one = EXAMPLES["obs.tap_back"]
    put(store, "obs.tap_back", one, at(TODAY - timedelta(days=1), 9), source="hub", quality=1.0)
    two = {**one, "levels": [{**lv, "band": "again", "tries": 2} if lv["level"] == 3 else lv for lv in one["levels"]],
           "levels_passed": 2, "error_pct": 9.4}
    put(store, "obs.tap_back", two, at(TODAY, 9), source="hub", quality=1.0)
    put(store, "obs.tap_back", {**one, "levels_passed": 3, "error_pct": 2.0}, at(TODAY, 18), source="hub", quality=0.2)
    h = history.build(store, "h", 30, now=NOW)
    assert [g.key for g in h.groups] == ["robot"]
    m = measures(h)
    assert set(m) == {"tap_back_songs", "tap_back_timing"}                 # and no drum measure at all
    songs, timing = m["tap_back_songs"], m["tap_back_timing"]
    assert (songs["title"], songs["unit"], songs["devices"]) == ("Tap it back: songs on the beat", "songs", ["robot"])
    assert [(d["date"], d["value"]) for d in songs["days"]] == [(str(TODAY - timedelta(days=1)), 3.0), (str(TODAY), 2.0)]
    assert [(d["value"], d["sessions"]) for d in timing["days"]] == [(3.8, 1), (9.4, 1)]   # the doubtful one is left out
    assert timing["title"] == "Tap it back: timing" and timing["decimals"] == 1
    assert len(songs["sessions"]) == 3                                     # ... of the day, but still listed
    latest = {v["key"]: v["value"] for v in songs["sessions"][-1]["values"]}
    assert latest == {"levels_passed": 3.0, "levels_played": 3.0, "error_pct": 3.8, "steadiness": 0.94, "taps": 40.0,
                      "duration_s": 78.0}
    body = h.model_dump(mode="json")
    assert_numbers_only(body)
    text = str(body).lower()
    assert not any(word in text for word in ("perfect", "great", "nice", "again", "band", "tries"))


def test_tap_it_back_feeds_no_metric_and_changes_no_reading():
    """Stored and shown, never scored (D51): no criteria metric reads it, and adding one changes nobody's state."""
    from kaiku_contracts import EXAMPLES
    from kaiku_contracts.sources import SOURCE_OF

    crit = service.file_criteria()
    assert SOURCE_OF["obs.tap_back"] == "robot"
    assert not [m.name for m in crit.metrics if m.obs == "obs.tap_back"]
    assert not [r.name for r in crit.rules if r.obs == "obs.tap_back"]
    store = Store(":memory:")
    single_person.populate(store, single_person.build(END), END)

    def reading():
        c = service.evaluate_home(store, single_person.HOME, crit, today=TODAY)["consensus"]
        return c["state"], [(v["source"], v["verdict"], v.get("days_with_data")) for v in c["sources"]]

    before = reading()
    put(store, "obs.tap_back", EXAMPLES["obs.tap_back"], at(END, 9, 30), source="hub", home=single_person.HOME,
        quality=1.0)
    assert reading() == before
