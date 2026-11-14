"""Camera face signs in the intelligence layer (D52): stored with provenance, compared with the person's own usual,
shown to her and to the practitioner, citable by the review under rules that forbid reading a feeling off a face,
a words-only cue for the companion, and never a vote. (The verdict pins are in test_single_person.py.)"""
import json
import re
from datetime import UTC, date, datetime, time, timedelta

import pytest
from kaiku_cloud import clinician_chat, course, debug_day, history, insight, service
from kaiku_cloud.analytics import consensus
from kaiku_cloud.analytics.verdict import verdict_for
from kaiku_cloud.jobs import single_person
from kaiku_cloud.mind import assemble, card, face_cue, feel
from kaiku_cloud.settings import TZ, Settings
from kaiku_cloud.store.db import Store
from kaiku_contracts import make
from kaiku_contracts.api import ContextCard, FeelPlan, PersonHistory, RecordCitation
from kaiku_contracts.criteria import parse_criteria
from kaiku_contracts.registry import EXAMPLES, FACE_EXAMPLES

END = date(2026, 11, 13)
FIRST = END - timedelta(days=15)
TODAY = END + timedelta(days=1)
NOW = datetime.combine(TODAY, time(20, 0), TZ)
SETTINGS = Settings(db_path=":memory:", llm="template")
NUMBER = re.compile(r"\d")
FACE_WORD = re.compile(r"face|camera|smil|blink|brow|gaze|express", re.I)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture(scope="module")
def rows():
    return single_person.build(END)


@pytest.fixture
def aino(rows):
    store = Store(":memory:")
    single_person.populate(store, rows, END)
    return store


def today(store, kind):
    store.insert_events(single_person.today_events(TODAY, kind, now=NOW))
    service.recompute_home(store, SETTINGS, "aino", TODAY)
    return store


def insight_of(store, **kw):
    row = service.recompute_home(store, SETTINGS, "aino", TODAY)
    return insight.insight(store, SETTINGS, "aino", row, generate=kw.pop("generate", False), now=NOW, **kw)


def ref(id_, label, detail="x", metric=None, source="laptop"):
    return RecordCitation(id=id_, label=label, detail=detail, metric=metric, source=source)


# ------------------------------------------------------------------------------------- ingest and the task route
def test_face_signs_are_accepted_stored_with_provenance_and_served_beside_their_task(client):
    game = make("obs.play_session", EXAMPLES["obs.play_session"], source="phone", home_id="h", sim=True)
    face = make("obs.face_signs", {**EXAMPLES["obs.face_signs"], "task": "firefly", "ref": str(game.id)}, source="phone",
                home_id="h", sim=True, quality=0.94)
    body = {"events": [e.model_dump(mode="json", exclude_none=True) for e in (game, face)]}
    assert client.post("/v1/events", json=body).json()["accepted"] == 2
    tasks = client.get("/v1/patients/h/tasks").json()
    assert [e["id"] for e in tasks["observations"]] == [str(game.id)]
    (sent,) = tasks["face_signs"]
    assert sent["payload"]["ref"] == str(game.id) and sent["quality"] == 0.94 and sent["sim"] is True
    assert sent["payload"]["method"] == "arkit_blendshapes" and sent["source"] == "phone"
    bad = make("obs.face_signs", EXAMPLES["obs.face_signs"], source="phone", home_id="h").model_dump(mode="json")
    bad["payload"]["frames"] = ["...jpeg..."]
    refused = client.post("/v1/events", json={"events": [bad]}).json()  # a picture can never be sent or kept
    assert refused["accepted"] == 0 and len(refused["rejected"]) == 1
    assert "jpeg" not in client.get("/v1/events", params={"home_id": "h"}).text
    cov = client.get("/v1/patients/h/insight", params={"generate": "false"}).json()["coverage"]
    apps = next(g for g in cov["groups"] if g["source"] == "laptop")
    assert {t["type"]: t["count"] for t in apps["types"]}["obs.face_signs"] == 1


def test_a_home_with_only_face_signs_has_no_group_with_enough_data(client):
    """Face signs add no coverage: fourteen days of nothing but camera numbers give the Apps group no reading."""
    events = []
    for back in range(14):
        ts = datetime.now(UTC) - timedelta(days=back, hours=1)
        events.append(make("obs.face_signs", FACE_EXAMPLES["check_in"], source="phone", home_id="lone", sim=True,
                           quality=0.97, ts=ts).model_dump(mode="json", exclude_none=True))
    assert client.post("/v1/events", json={"events": events}).json()["accepted"] == 14
    c = client.get("/v1/patients/lone/consensus").json()
    assert c["state"] == "watch" and c["agreement"] == "low_coverage"
    assert {v["verdict"] for v in c["sources"]} == {"insufficient"} and all(v["confidence"] == 0 for v in c["sources"])


def test_each_measure_reads_one_method_and_one_kind_of_task_and_the_two_methods_never_share_a_usual(client):
    """What the apps send (their own facts, 2026-11-14): the landmark method (Mac, iPhones without TrueDepth) has no
    smile, brow or gaze sign, and its blink rate, head movement and range are on other scales than ARKit's. So a
    game and a check-in from each method land in four different measures, and nothing pools them."""
    day = datetime.now(UTC) - timedelta(hours=2)
    landmark_game = FACE_EXAMPLES["landmarks"]                                    # firefly on the Mac
    landmark_chat = {**FACE_EXAMPLES["landmarks"], "task": "check_in", "expression_range": 0.41}  # no ref: a check-in
    arkit_game = {k: v for k, v in EXAMPLES["obs.face_signs"].items() if k != "ref"}  # lantern on the phone
    arkit_chat = FACE_EXAMPLES["check_in"]
    spoken = {**FACE_EXAMPLES["check_in"], "task": "tell"}                        # stored and listed, read by no measure
    sent = [make("obs.face_signs", p, source=src, home_id="both", sim=True, quality=p["coverage"], ts=day)
            for p, src in ((landmark_game, "laptop"), (landmark_chat, "laptop"), (arkit_game, "phone"),
                           (arkit_chat, "phone"), (spoken, "phone"))]
    body = {"events": [e.model_dump(mode="json", exclude_none=True) for e in sent]}
    assert client.post("/v1/events", json=body).json()["accepted"] == 5
    series = {s["metric"]: [p["value"] for p in s["points"] if p["value"] is not None]
              for s in client.get("/v1/patients/both/timeline").json()["series"] if s["metric"].startswith("face")}
    assert series == {"face_range": [0.34], "face_smiles": [0.12], "face_blinks": [14.5],
                      "face_range_chat": [0.52], "face_smiles_chat": [0.21],
                      "face_range_landmarks": [0.27], "face_range_chat_landmarks": [0.41]}
    crit = service.active_criteria(Store(":memory:"))
    for m in crit.shown_for("laptop"):  # a landmark measure reads only what that method sends
        if m.where["method"] == "vision_landmarks":
            assert m.field == "expression_range", m.name
    camera = next(g for g in client.get("/v1/me/history", params={"home_id": "both"}).json()["groups"]
                  if g["key"] == "camera")
    devices = {m["key"]: m["devices"] for m in camera["measures"]}
    assert devices["face_range_landmarks"] == ["mac"] == devices["face_range_chat_landmarks"]
    assert devices["face_range"] == ["phone"] == devices["face_smiles_chat"]
    mac_session = next(m for m in camera["measures"] if m["key"] == "face_range_chat_landmarks")["sessions"][0]
    assert not {"smile_share", "smiles", "gaze_on_share", "brow_raise_share"} & {v["key"] for v in mac_session["values"]}


# ----------------------------------------------------------------------------- one line of config lets one vote
def test_deleting_the_role_line_lets_a_face_metric_vote_and_count(aino):
    crit = service.active_criteria(aino)
    raw = crit.model_dump(mode="json", by_alias=True)
    block = next(m for m in raw["metric"] if m["name"] == "face_smiles")
    del block["role"]
    voting = parse_criteria(raw)
    assert voting.rule_version != crit.rule_version and voting.metric("face_smiles").votes
    events, actions = aino.events_for_home("aino"), aino.actions("aino")
    from kaiku_cloud.analytics.data import build

    shown, voted = build("aino", events, crit, actions), build("aino", events, voting, actions)
    assert shown.source_days["laptop"].keys() <= voted.source_days["laptop"].keys()
    assert voted.source_days["laptop"] != shown.source_days["laptop"]  # the type now counts toward its group

    # Leave the Apps group nothing but the camera and let one drifting face metric be enough for "worse": with the
    # role line the group has no reading at all; without it, it is worse on the quiet days, citing the smiles.
    def camera_only(c):
        raw = c.model_dump(mode="json", by_alias=True)
        raw["sources"]["laptop"]["worse_min_weight"] = 0.2
        raw["metric"] = [m for m in raw["metric"] if m["obs"] in ("obs.face_signs", "obs.self_report", "obs.outing",
                                                                  "obs.wearable_daily")]
        raw["rule"] = []
        return parse_criteria(raw)

    faces = [e for e in events if e["type"] == "obs.face_signs"]
    day = FIRST + timedelta(days=12)
    off, on = camera_only(crit), camera_only(voting)
    assert verdict_for(build("aino", faces, off, actions), "laptop", day, off, NOW).model.verdict == "insufficient"
    worse = verdict_for(build("aino", faces, on, actions), "laptop", day, on, NOW).model
    assert worse.verdict == "worse" and [e.metric for e in worse.evidence] == ["face_smiles"]
    assert worse.evidence[0].summary.startswith("Smiling in games (camera) lower than usual on 4 of the last 5 days")


# --------------------------------------------------------------------------------- practitioner: trends and course
def test_trends_carry_the_face_measures_marked_as_not_scored(client):
    end = datetime.now(TZ).date() - timedelta(days=1)
    single_person.seed("http://127.0.0.1:8000", single_person.build(end), reset=True, jobs=False, client=client)
    series = {s["metric"]: s for s in client.get("/v1/patients/aino/timeline", params={"days": 30}).json()["series"]}
    for name in ("face_range", "face_smiles", "face_blinks", "face_range_chat", "face_smiles_chat"):
        s = series[name]
        assert s["scored"] is False and s["source"] == "laptop" and "camera" in s["label"]
    assert series["mood"]["scored"] is True and series["lantern_speed"]["scored"] is True
    banded = [p for p in series["face_smiles"]["points"] if p["band_low"] is not None and p["value"] is not None]
    assert len(banded) >= 8 and sum(p["value"] < p["band_low"] for p in banded) == 4  # the four quiet days


def test_the_course_tells_face_signs_as_their_own_events_and_never_lets_them_lead(aino):
    out = insight_of(aino)
    arc = out.course
    face = [e for e in arc.events if (e.metric_id or "").startswith("face_")]
    assert {(e.metric_id, e.kind) for e in face} == {(m, k) for m in ("face_range", "face_smiles", "face_blinks")
                                                     for k in ("onset", "back_in_range")}
    assert all(e.text.endswith(course.SHOWN_NOTE.strip()) and e.group == "laptop" for e in face)
    smiles = next(e for e in face if e.metric_id == "face_smiles" and e.kind == "onset")
    assert smiles.text == "Smiling in games first below their usual on 7 Nov: 4% (usual 14%). Shown only: no vote in the consensus."
    assert not any((e.metric_id or "").startswith("face_") for e in arc.events if e.kind == "lowest")
    # what moved, what is back and what moved first are the scored measures'
    without = Store(":memory:")
    single_person.populate(without, [r for r in single_person.build(END) if r["type"] != "obs.face_signs"], END)
    plain = insight_of(without).course
    assert (arc.moved, arc.back, arc.low_date, arc.phase) == (plain.moved, plain.back, plain.low_date, plain.phase)
    assert arc.summary.split(" Shown, not scored:")[0] in plain.summary
    # one sentence for everything that is shown and not scored (the face signs here, the day from Apple Health too)
    told = re.search(r"Shown, not scored: ([^.]+) were away from their usual from 7 Nov and are back within it\.",
                     arc.summary)
    assert told and "expressiveness in games" in told.group(1)
    faceless = re.search(r"Shown, not scored: ([^.]+) were away", plain.summary)
    assert faceless and "games" not in faceless.group(1)  # without the face records the sentence has none of them
    assert out.status_line == insight_of(without).status_line
    assert not {"face_range", "face_smiles", "face_blinks"} & set(out.comparison.back_in_range)
    first = [e for e in out.graph.edges if e.rel == "moved_first"]
    assert first and not any("face_" in e.dst for e in first)
    assert {e.dst for e in out.graph.edges if e.rel == "followed"} >= {"measure:face_smiles", "measure:face_range"}


def test_the_week_comparison_lists_them_and_counts_only_what_the_verdict_reads(aino):
    out = insight_of(aino)
    apps = next(g for g in out.comparison.groups if g.source == "laptop")
    shown = [m for m in apps.metrics if m.metric.startswith("face_")]
    assert {m.metric for m in shown} == {"face_range", "face_smiles", "face_blinks", "face_range_chat", "face_smiles_chat"}
    assert all(m.meaning.endswith("Shown only: no vote in the consensus.") for m in shown)
    assert "5 more are shown without a vote." in apps.meaning
    assert not {m.metric for m in shown} & {*out.comparison.improved, *out.comparison.changed}
    nodes = {n.id: n for n in out.graph.nodes}
    assert nodes["measure:face_smiles"].domain == "screens" and len(nodes["measure:face_smiles"].days) == 16
    labels = {e.dst: e.label for e in out.graph.edges if e.rel == "measures"}
    assert labels["measure:face_smiles"].endswith("shown not scored") and "shown" not in labels["measure:lantern_speed"]
    # the care-team week view speaks of what the rule reads
    from kaiku_cloud import week

    w = week.week(aino, SETTINGS, "aino", "care_team", NOW)
    assert not [i for i in [*w.going_well, *w.worth_a_look] if (i.metric or "").startswith("face_")]
    assert not any("camera" in s.why.lower() or "smil" in s.why.lower() for s in w.next_steps)
    assert {c.label for s in w.sources if s.source == "laptop" for c in s.counts} >= {"camera readings during tasks"}
    person = week.week(aino, SETTINGS, "aino", "person", NOW).model_dump(mode="json")
    counts = [c for s in person.pop("sources") for c in s["counts"] if FACE_WORD.search(c["label"])]
    assert [c["label"] for c in counts] == ["camera readings during tasks"]  # a count of her own records, as in History
    assert not FACE_WORD.search(json.dumps(person))  # and not a word about her face anywhere else in her own week


# ----------------------------------------------------------------------------------------- practitioner: the review
ALLOWED = {
    "source:robot": ref("source:robot", "Check-ins & robot", source="robot"),
    "course:onset:mood": ref("course:onset:mood", "Mood dial", "Mood dial first below their usual on 7 Nov.", "mood", "robot"),
    "week:mood": ref("week:mood", "Mood dial", "Mood dial 2 of 5 this week.", "mood", "robot"),
    "course:onset:face_smiles": ref("course:onset:face_smiles", "Smiling in games",
                                    "Smiling in games first below their usual on 7 Nov.", "face_smiles"),
    "course:back_in_range:face_smiles": ref("course:back_in_range:face_smiles", "Smiling in games",
                                            "Smiling in games back within their usual from 11 Nov.", "face_smiles"),
    "week:face_range": ref("week:face_range", "Expressiveness in games", "Expressiveness in games 0.2 this week.", "face_range"),
    "course:back_in_range:mood": ref("course:back_in_range:mood", "Mood dial", "Mood dial back within their usual.", "mood", "robot"),
}
TONE = {"source:robot": "worse", "course:onset:mood": "worse", "week:mood": "worse", "course:onset:face_smiles": "worse",
        "course:back_in_range:face_smiles": "better", "week:face_range": "worse", "course:back_in_range:mood": "better"}
SHOWN = {"face_smiles", "face_range"}
SUSTAINED = {"source:robot", "course:onset:mood", "week:mood"}


def finding(theme, cites, meaning, consider=None):
    return insight.check_finding({"theme": theme, "cites": cites, "meaning": meaning, "consider": consider},
                                 ALLOWED, TONE, SUSTAINED, None, SHOWN)


def test_a_face_record_is_citable_beside_a_scored_one():
    ok = finding("change", ["source:robot", "course:onset:mood", "course:onset:face_smiles"],
                 "The mood dial moved below their usual first, and smiling in games dropped on the same days; both "
                 "came after the short nights.", "Ask how those days were and what the evenings looked like.")
    assert not isinstance(ok, str) and ok.cites[-1] == "course:onset:face_smiles"
    assert "Smiling in games first below their usual on 7 Nov." in ok.facts


@pytest.mark.parametrize(("theme", "cites", "meaning", "why"), [
    # a finding cannot rest on the camera alone
    ("change", ["course:onset:face_smiles", "week:face_range"],
     "Smiling in games and expressiveness in games both dropped first and stayed below usual through the week.",
     "unscored_only"),
    # a shown record never decides the theme: nothing scored here is sustained
    ("change", ["course:back_in_range:mood", "course:onset:face_smiles"],
     "The mood dial came back within usual while smiling in games first dropped earlier in the same week.",
     "direction_mismatch"),
    # a shown record that came back does not make an improvement out of a scored one that is still worse
    ("improvement", ["week:mood", "course:back_in_range:face_smiles"],
     "Smiling in games came back within usual after the care team's call while the mood dial still lags behind.",
     "direction_mismatch"),
    # no emotion may be named, about a face or anything else
    ("change", ["source:robot", "course:onset:mood", "course:onset:face_smiles"],
     "The mood dial moved first and smiling in games followed, so she was sad through those days.", "emotion_label"),
    ("change", ["source:robot", "course:onset:mood", "course:onset:face_smiles"],
     "The mood dial dropped first and the camera then showed a happy face returning after the call.", "emotion_label"),
    ("change", ["source:robot", "course:onset:mood", "week:face_range"],
     "The mood dial moved first and a flat affect followed in the games on the same days.", "emotion_label"),
    # nor may a state be read off the face
    ("change", ["source:robot", "course:onset:mood", "course:onset:face_smiles"],
     "The mood dial moved first; fewer smiles in games then show that she looked withdrawn that week.", "face_inference"),
    ("change", ["source:robot", "course:onset:mood", "week:face_range"],
     "The mood dial moved first and less facial expressiveness followed, which suggests she felt low.", "face_inference"),
    ("change", ["source:robot", "course:onset:mood", "course:onset:face_smiles"],
     "The mood dial moved first and smiling in games followed, so her mood was clearly lower then.", "face_inference"),
])
def test_what_the_review_may_not_do_with_a_face(theme, cites, meaning, why):
    assert finding(theme, cites, meaning) == why


def test_the_face_wording_checks_leave_ordinary_review_prose_alone():
    for prose in ("Late-night screen time moved first and sleep shortened the next day; mood and outings followed.",
                  "Mood and walks are back within her usual, sleep is the one still lagging.",
                  "Smiling in games dropped the same days as the mood dial and came back after the care team's call.",
                  "Blink rate in games rose while expressiveness in games narrowed, and both returned later.",
                  "Ask what the late nights before the dip were about, and whether sleep is still short."):
        assert insight.prose_issue(prose) is None, prose
    assert insight.face_issue("She seemed tired in the games.") is None  # no face word: other checks own this
    assert insight.face_issue("Her face seemed tired in the games.") == "face_inference"


def test_the_review_receives_face_records_marked_unscored_and_keeps_only_what_passes(aino):
    sent = {}

    def gen(prompt, **_kw):
        context = json.loads(prompt.split("EVIDENCE:\n", 1)[1].split("\nYour previous response")[0])
        sent["context"] = {c["id"]: c for c in context}
        sent["prompt"] = prompt
        return json.dumps({"findings": [
            {"theme": "change", "cites": ["source:robot", "course:onset:mood", "course:onset:face_smiles"],
             "meaning": "The mood dial moved below their usual after the short nights, and smiling in games dropped "
                        "on the same days and came back later.",
             "consider": "Ask how those days were at home."},
            {"theme": "change", "cites": ["course:onset:face_smiles", "course:onset:face_range"],
             "meaning": "Smiling in games and expressiveness in games both dropped first and stayed below usual."},
            {"theme": "change", "cites": ["source:robot", "course:onset:energy", "course:onset:face_range"],
             "meaning": "The energy dial moved first and her face then looked sad and flat in the games that week."},
        ]})

    out = insight_of(aino, generate=True, gen=gen)
    ctx = sent["context"]
    assert ctx["course:onset:face_smiles"]["scored"] is False and ctx["course:onset:face_smiles"]["sustained"] is False
    assert ctx["course:onset:face_smiles"]["direction"] == "worse" and "scored" not in ctx["course:onset:mood"]
    scored_part = [c for c in ctx.values() if c.get("scored") is not False]
    beside = int(insight.cfg("max_shown_evidence", 8))
    assert 0 < len(ctx) - len(scored_part) <= beside and len(scored_part) <= 60  # they ride along; they take no place
    assert "A face does not show what a person feels" in sent["prompt"]
    assert out.review.by == "gemma"
    kept = [f for f in out.review.findings if f.by == "gemma"]
    assert len(kept) == 1 and "course:onset:face_smiles" in kept[0].cites
    assert ("Smiling in games first below their usual on 7 Nov: 4% (usual 14%). Shown only: no vote in the consensus."
            in kept[0].facts)
    check = next(s for s in out.trace if s.step == "validate")
    assert check.rejected.get("unscored_only") == 1 and check.rejected.get("emotion_label") == 1
    assert any(r.id == "course:onset:face_smiles" for r in out.evidence)  # the cited record is served beside it
    assert out.state == "needs_call" and out.rule_version == service.active_criteria(aino).rule_version


def test_the_template_review_never_builds_on_a_face_measure(aino):
    out = insight_of(aino)
    assert out.review.by == "template"
    assert not any("face_" in c for f in out.review.findings for c in f.cites)
    assert not any(FACE_WORD.search(f.meaning) for f in out.review.findings)


def test_clinician_chat_describes_the_capture_and_the_counts_and_no_feeling(aino):
    refs = clinician_chat.evidence(aino, SETTINGS, "aino", service.recompute_home(aino, SETTINGS, "aino", TODAY), NOW)
    tasks = {r.label: r for r in refs if r.id.startswith("task:")}
    lantern = tasks["Lantern task on phone"]
    assert "Camera face signs: one usable face in" in lantern.detail and "frames looked at over" in lantern.detail
    assert "smiling in" in lantern.detail and "blinks a minute" in lantern.detail and lantern.unit == "ratio"
    assert lantern.detail.endswith("not an emotion or wellbeing measure, and no vote in the consensus.")
    assert "Check-in chat on phone" in tasks
    metric = next(r for r in refs if r.id == "metric:face_smiles")
    assert metric.label == "Smiling in games (camera) (Apps)" and "their usual" in metric.detail
    assert "infer emotions" in clinician_chat._SYSTEM and "never as a reading of how the person felt" in clinician_chat._SYSTEM


# ------------------------------------------------------------------------------------------------ her own History
def test_history_has_a_camera_group_with_her_own_numbers_and_nothing_else(aino):
    h = history.build(aino, "aino", 30, NOW)
    PersonHistory.model_validate(h.model_dump(mode="json"))
    groups = {g.key: g for g in h.groups}
    assert list(groups)[-1] == "camera" and groups["camera"].title == "Camera during activities"
    m = {x.key: x for x in groups["camera"].measures}
    assert list(m) == ["face_smiles", "face_range", "face_blinks", "face_smiles_chat", "face_range_chat"]
    crit = service.active_criteria(aino)
    data = service.patient_data(aino, "aino", crit, TODAY)
    for key, measure in m.items():  # the numbers the practitioner side has, day for day
        assert {d.date: d.value for d in measure.days} == pytest.approx(data.series[key]), key
        assert measure.devices == ["phone"] and measure.sim
    assert m["face_smiles"].usual is not None and m["face_smiles_chat"].usual is None  # five chats: no usual yet
    assert m["face_smiles"].title == "Smiling during games" and m["face_range"].per_day == "average"
    newest = m["face_smiles"].sessions[0]
    assert newest.label in ("Lantern", "Firefly", "Pebble path", "Seed shelf", "Watering")
    values = {v.key: v for v in newest.values}
    assert {"smile_share", "smiles", "expression_range", "blinks_per_min", "coverage", "samples", "duration_s"} <= values.keys()
    assert values["samples"].title == "Pictures looked at, none kept"
    # the session with too little of her face in view is listed with what the camera could use, and not in the day
    thin = next(s for s in m["face_smiles"].sessions if next(v.value for v in s.values if v.key == "coverage") < .6)
    day = next(d for d in m["face_smiles"].days if d.date == thin.ts.astimezone(TZ).date())
    that_day = [r["payload"] for r in single_person.build(END) if r["type"] == "obs.face_signs"
                and r["ts"][:10] == str(day.date) and r["payload"]["task"] not in ("check_in", "tell")]
    assert day.sessions == len(that_day) - 1 == sum(1 for p in that_day if p["coverage"] >= .6)
    # numbers and plain names for movements: no word for a feeling, a judgement or a direction anywhere in the group
    words = [groups["camera"].title]
    for x in groups["camera"].measures:
        words += [x.title, x.unit, *(s.label or "" for s in x.sessions), *(v.title + " " + v.unit for s in x.sessions for v in s.values)]
    assert not re.search(r"emotion|mood|feel|sad|happy|quiet|flat|low\b|worse|better|usual|score|flag|state|verdict",
                         " | ".join(words), re.I)
    assert not {"z", "verdict", "direction", "scored", "role", "weight"} & set(PersonHistory.model_json_schema()["$defs"]["HistoryMeasure"]["properties"])
    # the older face fields of a play session stay out of every other group
    for g in h.groups:
        if g.key != "camera":
            keys = {v.key for x in g.measures for s in x.sessions for v in s.values}
            assert not {k for k in keys if FACE_WORD.search(k)}, g.key


# ---------------------------------------------------------------------------------------------- developers' day
def test_the_debug_day_lists_the_face_records_their_readings_and_that_they_never_vote(aino):
    day = FIRST + timedelta(days=11)  # the first "needs a call" day: one game, the lantern
    d = debug_day.build(aino, SETTINGS, "aino", day, now=NOW)
    (event,) = [e for e in d.events if e.type == "obs.face_signs"]
    assert event.metrics == ["face_range", "face_smiles", "face_blinks"] and event.payload["task"] == "lantern"
    assert event.quality == event.payload["coverage"]
    metrics = {m.metric: m for m in d.metrics}
    smiles = metrics["face_smiles"]
    assert smiles.enabled and not smiles.scored and not smiles.flagged and smiles.status == "drifting"
    assert smiles.beyond_today and smiles.readings == 1 and smiles.event_ids == [event.id]
    facts = {f.id: f for f in d.facts}
    assert facts["metric:face_smiles"].detail.endswith("observe-only, never a vote.")
    assert facts["metric:face_smiles"].flags == {"scored": False, "beyond": True, "within": False}
    line = facts[f"event:{event.id}"]
    assert line.label.startswith("obs.face_signs at") and "smile_share" in line.detail and "coverage" in line.detail
    assert line.detail.endswith("counted toward face_range, face_smiles, face_blinks.")
    apps = next(v for v in d.verdicts if v.source == "laptop")
    scored_drifting = sum(m.weight for m in d.metrics if m.source == "laptop" and m.scored and m.status == "drifting")
    assert apps.worse_weight == pytest.approx(scored_drifting)  # the face measures drift and add no weight
    replayed = consensus.replay(service.patient_data(aino, "aino", service.active_criteria(aino), TODAY),
                                service.active_criteria(aino), day, d.day_end)
    assert d.consensus.state == replayed[-1].state
    # a capture too thin to count is still listed, and says what it counted toward: nothing
    thin_day = FIRST + timedelta(days=5)
    blank = next(e for e in debug_day.build(aino, SETTINGS, "aino", thin_day, now=NOW).events
                 if e.type == "obs.face_signs" and e.payload["coverage"] < .6)
    assert blank.metrics == []
    thin_facts = {f.id: f for f in debug_day.build(aino, SETTINGS, "aino", thin_day, now=NOW).facts}
    assert thin_facts[f"event:{blank.id}"].detail.endswith("counted toward no measure.")


# ---------------------------------------------------------------------------------------------- the companion cue
def test_a_clearly_quieter_face_today_reaches_the_companion_as_a_cue_for_manner_only(aino):
    store = today(aino, "rough")
    assert face_cue.quieter_in(store, "aino", NOW) == ["games"]
    c = card.build_card(store, SETTINGS, "aino", now=NOW, purpose="talk")
    assert c.quieter_in == ["games"] and c.tone in ("gentle", "extra-gentle")
    wire = c.model_dump(mode="json")
    assert wire["quieter_in"] == ["games"]
    for key, value in wire.items():  # nothing else on the card knows about a face, and no value is a number
        assert not FACE_WORD.search(key), key
        if key != "quieter_in":
            assert not FACE_WORD.search(json.dumps(value)), key
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in wire.values())
    text = assemble.assemble_from_files("iphone", card.card_dict(c))
    line = assemble.QUIET_LINE.format(where="today's games")
    assert line in text and "never mention their face or a camera" in line
    assert not NUMBER.search(line)
    today_section = text.split("## Today\n", 1)[1].split("\n## ", 1)[0]
    assert not re.search(r"smil|blink|express|coverage|\d\s*%", today_section)  # what was counted never crosses
    # the `feel` plan carries the same kind of cue, as fixed words
    prep = feel.prepare(store, "aino", NOW)
    assert prep["quiet"] == ["games"]
    plan = feel.act(store, "aino", "iphone", None, None,
                    {"kind": "flat", "heard": {"valence": "neutral"}, "said": "Nothing much."}, NOW)
    FeelPlan.model_validate(plan)
    assert plan["manner"] == feel.MANNER and not NUMBER.search(plan["manner"])
    assert "never mention their face or a camera" in plan["manner"] and "games" not in plan["manner"]


def test_the_cue_holds_only_when_the_rule_holds(aino, rows):
    # nothing recorded today: nothing to be quieter in (the record ends yesterday)
    assert face_cue.quieter_in(aino, "aino", NOW) == []
    assert card.build_card(aino, SETTINGS, "aino", now=NOW).quieter_in == []
    assert "manner" not in feel.act(aino, "aino", "iphone", None, None,
                                    {"kind": "flat", "heard": {"valence": "neutral"}}, NOW)
    text = assemble.assemble_from_files("iphone", card.card_dict(card.build_card(aino, SETTINGS, "aino", now=NOW)))
    assert "For your manner only" not in text
    # her usual face today: no cue
    usual = Store(":memory:")
    single_person.populate(usual, rows, END)
    assert face_cue.quieter_in(today(usual, "good"), "aino", NOW) == []

    def with_today(payload, quality=0.95, store=None):
        store = store or Store(":memory:")
        if not store.home_ids():
            single_person.populate(store, rows, END)
        store.insert_events([make("obs.face_signs", payload, source="phone", home_id="aino", sim=True, quality=quality,
                                  ts=NOW - timedelta(hours=2)).model_dump(mode="json", exclude_none=True)])
        return store

    quiet = single_person.face_payload("lantern", 90.0, 0.95, 0.95, lambda _k, _s: 0.0)
    assert face_cue.quieter_in(with_today(quiet), "aino", NOW) == ["games"]
    # too little of her face in view, too few frames, too short: a thin capture can never set it
    assert face_cue.quieter_in(with_today({**quiet, "coverage": 0.4}, 0.4), "aino", NOW) == []
    assert face_cue.quieter_in(with_today({**quiet, "samples": 30}), "aino", NOW) == []
    assert face_cue.quieter_in(with_today({**quiet, "duration_s": 8.0}), "aino", NOW) == []
    # one sign clearly below while the other is above her usual: not "clearly quieter"
    mixed = {**quiet, "expression_range": 0.45}
    assert face_cue.quieter_in(with_today(mixed), "aino", NOW) == []
    # below, but not clearly (about one spread): no cue
    slight = single_person.face_payload("lantern", 90.0, 0.3, 0.95, lambda _k, _s: 0.0)
    assert face_cue.quieter_in(with_today(slight), "aino", NOW) == []
    # the other method has no usual of its own here: never compared with the phone's
    assert face_cue.quieter_in(with_today({**FACE_EXAMPLES["landmarks"], "expression_range": 0.01, "smile_share": 0.0}),
                               "aino", NOW) == []
    # a check-in with a quiet face, but only five chats on record: no established usual, no cue
    chat = single_person.face_payload("check_in", 120.0, 1.0, 0.96, lambda _k, _s: 0.0, talking=True)
    assert face_cue.quieter_in(with_today(chat), "aino", NOW) == []
    # a young record (only the provisional early baseline): never
    young = Store(":memory:")
    single_person.populate(young, [r for r in rows if r["ts"][:10] >= str(FIRST + timedelta(days=8))], END)
    assert face_cue.quieter_in(with_today(quiet, store=young), "aino", NOW) == []
    # someone else in the room: the card is not told, and nothing about it is rendered
    seen = today(with_today(quiet), "rough")
    shared = card.build_card(seen, SETTINGS, "aino", now=NOW, others_present=True)
    assert shared.quieter_in == []
    assert "For your manner only" not in assemble.assemble_from_files("iphone", card.card_dict(shared))


def test_the_card_cannot_carry_face_data_under_any_key():
    base = {"tone": "steady", "language": "en"}
    for key in ("face_smiles", "smile_share", "camera", "expression_range", "blinks_per_min", "facial", "gaze_on"):
        assert assemble.FORBIDDEN_KEY.search(key), key
        with pytest.raises(ValueError, match="not allowed"):
            assemble.validate_card({**base, key: 0.1})
    for bad in (["lantern"], ["games", "games"], "games", [0.04], ["smiles down"]):
        with pytest.raises(ValueError, match="quieter_in"):
            assemble.validate_card({**base, "quieter_in": bad})
    assemble.validate_card({**base, "quieter_in": ["games", "check_in"]})
    assert set(ContextCard.model_fields["quieter_in"].annotation.__args__[0].__args__) == set(assemble.QUIETER_IN)
    both = assemble.render_card({**base, "quieter_in": ["check_in", "games"]})
    assert "today's games and today's check-in" in both


def test_the_persona_tells_kaiku_it_never_sees_a_face_and_what_to_say_when_asked():
    persona, _surfaces = assemble.load_files()
    limits = assemble.parse_persona(persona)["sections"]["Hard limits (never)"]
    assert "never comment on their face" in limits.lower() and "camera during activities" in limits.lower()
    from kaiku_contracts import wording

    answer = re.search(r'"(I can\'t see you\.[^"]+)"', limits).group(1)
    assert "numbers" in answer and "never pictures" in answer and "switch it off" in answer
    assert not wording.lint(answer, max_questions=None)  # the honest answer itself passes every wording rule
