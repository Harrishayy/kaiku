"""Attention ladder: nobody -> appeared -> approaching -> at_desk, greetings, offers and their edge cases."""

from datetime import datetime, timedelta, timezone

import pytest
from kaiku_contracts import make
from kaiku_hub.attention import Attention, AttentionConfig, greet_key

TZ = timezone(timedelta(hours=2))


def T(h: int, m: int = 0, s: float = 0.0) -> datetime:
    return datetime(2026, 11, 14, h, m, tzinfo=TZ) + timedelta(seconds=s)


def face(x=0.0, size=0.3, y=0.0):
    return {"x_norm": x, "y_norm": y, "size": size, "confidence": 0.9}


def walk_up(att: Attention, start: datetime, *, faces: int = 1, secs: float = 3.0, done=False, running=False):
    """Someone walks up: face grows from 0.05 to 0.35 over `secs` at 5 Hz. Returns (actions, time of last face)."""
    acts, steps = [], int(secs * 5)
    for i in range(steps + 1):
        t = start + timedelta(seconds=0.2 * i)
        size = 0.05 + 0.30 * i / steps
        for k in range(faces):
            att.add_face(face(x=-0.5 + 0.8 * k + 0.1 * i / steps, size=size), t)
        acts += att.tick(t, ritual_done_today=done, ritual_running=running)
    return acts, t


def says(acts):
    return [a[1] for a in acts if a[0] == "say"]


def heads(acts):
    return [a[1] for a in acts if a[0] == "head"]


def offered(acts):
    return any(a[0] == "offer" for a in acts)


def test_full_ladder_morning():
    att = Attention()
    acts, _ = walk_up(att, T(8))
    assert att.state == "at_desk"
    hs = heads(acts)
    assert hs[0] == {"eyes": "wide"}                                  # glance first
    assert any("purr" in h for h in hs)                               # then purr
    assert any("pan" in h for h in hs) and any("look" in h for h in hs)
    assert says(acts) == ["greet.morning"]                            # then greeting
    assert offered(acts)                                              # then the offer
    order = [a[0] if a[0] != "head" or "purr" not in a[1] else "purr" for a in acts]
    assert order.index("purr") < order.index("say") < order.index("offer")
    for h in hs:                                                      # every head command is valid
        make("cmd.head", h, source="hub")


def test_states_step_through():
    att = Attention()
    for sec, size, state in ((0, 0.05, "appeared"), (1, 0.15, "approaching"), (2, 0.3, "at_desk")):
        att.add_face(face(size=size), T(8, 0, sec))
        att.tick(T(8, 0, sec))
        assert att.state == state


@pytest.mark.parametrize("h,key", [(5, "greet.morning"), (11, "greet.morning"), (12, "greet.afternoon"),
                                   (17, "greet.evening"), (22, "greet.evening"), (23, "greet.night"),
                                   (2, "greet.night")])
def test_greet_key_by_time(h, key):
    assert greet_key(T(h)) == key


def test_flicker_shorter_than_lost_s_does_not_reset():
    att = Attention()
    _, t = walk_up(att, T(9))
    acts = att.tick(t + timedelta(seconds=1.9))          # face gone 1.9 s
    assert att.state == "at_desk" and not acts
    att.add_face(face(), t + timedelta(seconds=2.0))      # back: same visit, no second greeting
    acts = att.tick(t + timedelta(seconds=2.0))
    assert not says(acts) and not offered(acts)


def test_face_lost_longer_than_lost_s_resets_and_homes():
    att = Attention()
    _, t = walk_up(att, T(9))
    acts = att.tick(t + timedelta(seconds=2.1))
    assert att.state == "nobody"
    assert heads(acts) == [{"home": True, "eyes": "neutral"}]


def test_presence_keeps_visit_when_face_lost():
    att = Attention()
    _, t = walk_up(att, T(9))
    att.set_present(True)
    att.tick(t + timedelta(seconds=10))
    assert att.state == "at_desk"


def test_two_faces_hello_you_two_no_offer():
    att = Attention()
    acts, _ = walk_up(att, T(10), faces=2)
    assert says(acts) == ["greet.two"]
    assert not offered(acts)


def test_one_face_jitter_is_not_two_people():
    att = Attention()
    t = T(10)
    att.add_face(face(x=0.10), t)
    att.add_face(face(x=0.18), t + timedelta(seconds=0.1))
    assert att.face_count(t + timedelta(seconds=0.1)) == 1


def test_quiet_mode_no_purr_no_greeting_but_eyes_track():
    att = Attention()
    att.quiet(T(9))
    acts, _ = walk_up(att, T(9, 30))
    assert not says(acts) and not offered(acts)
    assert not any("purr" in h for h in heads(acts))
    assert any("look" in h for h in heads(acts))
    acts, _ = walk_up(Attention(quiet_until=T(9)), T(11, 1))  # quiet expired
    assert says(acts)


@pytest.mark.parametrize("h,m,greets", [(22, 59, True), (23, 0, False), (6, 59, False), (7, 0, True)])
def test_night_window_boundaries(h, m, greets):
    att = Attention()
    acts, _ = walk_up(att, T(h, m), secs=1.0)  # 1 s walk-up stays in the same minute
    assert bool(says(acts)) is greets
    assert offered(acts) is greets


def test_night_person_starts_then_greets_without_waiting():
    att = Attention()
    acts, t = walk_up(att, T(1))
    assert not says(acts)
    att.person_started(t)
    att.add_face(face(x=-0.4), t)
    acts = att.tick(t)
    assert says(acts) == ["greet.night"]


def test_night_window_disabled_when_equal():
    att = Attention(cfg=AttentionConfig(night_start="00:00", night_end="00:00"))
    assert not att.is_night(T(2))


@pytest.mark.parametrize("gap_min,greets", [(2 * 60 + 59, False), (3 * 60 + 1, True)])
def test_regreet_after_3h(gap_min, greets):
    att = Attention()
    _, t = walk_up(att, T(8))
    att.tick(t + timedelta(seconds=5))                    # leaves
    assert att.state == "nobody"
    acts, _ = walk_up(att, T(8) + timedelta(minutes=gap_min))
    assert bool(says(acts)) is greets


def test_ritual_done_today_greets_but_no_offer():
    att = Attention()
    acts, _ = walk_up(att, T(9), done=True)
    assert says(acts) == ["greet.morning"]
    assert not offered(acts)


def test_ritual_running_owns_the_body():
    att = Attention()
    acts, _ = walk_up(att, T(9), running=True)
    assert acts == [] and att.state == "at_desk"


def test_presence_without_camera_counts_as_at_desk():
    att = Attention()
    att.set_present(True)
    acts = att.tick(T(9))
    assert att.state == "at_desk" and says(acts) == ["greet.morning"] and offered(acts)


def test_pan_smoothing_and_deadband():
    att = Attention()
    t = T(9)
    pans = []
    for i in range(20):  # face stays at x=0.5 with tiny jitter
        att.add_face(face(x=0.5 + (0.01 if i % 2 else -0.01)), t)
        for _, cmd in [a for a in att.tick(t) if a[0] == "head"]:
            if "pan" in cmd:
                pans.append(cmd["pan"]["target_deg"])
        t += timedelta(seconds=0.2)
    assert pans and pans == sorted(pans)                   # converges monotonically, no back-and-forth
    assert abs(pans[-1] - 15.0) <= 4.0                     # x=0.5 of a 60 deg view = 15 deg
    assert len(pans) <= 5                                  # deadband: no twitching once there


def test_tracking_rate_limited():
    att = Attention()
    t = T(9)
    n = 0
    for i in range(10):  # 10 detections within 0.5 s
        att.add_face(face(x=0.1 * i), t + timedelta(seconds=0.05 * i))
        n += sum(1 for a in att.tick(t + timedelta(seconds=0.05 * i)) if a[0] == "head" and "look" in a[1])
    assert n <= 3


def test_night_window_accepts_toml_times_from_env():
    from datetime import time

    att = Attention(cfg=AttentionConfig(night_start=time(0, 0), night_end=time(0, 0)))
    assert not att.is_night(T(2))


def test_head_mounted_camera_tracks_relative_to_the_pan():
    """Camera on the head (current build): a face right of centre moves the head further from where it points."""
    att = Attention(cfg=AttentionConfig(camera_on_head=True, pan_smoothing=1.0, pan_deadband_deg=0.0))
    att.set_head_pan(40.0)
    att.add_face(face(x=0.5), T(9))
    pans = [a[1]["pan"]["target_deg"] for a in att.tick(T(9)) if a[0] == "head" and "pan" in a[1]]
    assert pans == [55.0]  # 40 + 0.5 * 60 / 2
    att2 = Attention(cfg=AttentionConfig(camera_on_head=True, pan_smoothing=1.0, pan_deadband_deg=0.0))
    att2.set_head_pan(95.0)
    att2.add_face(face(x=1.0), T(9))
    pans = [a[1]["pan"]["target_deg"] for a in att2.tick(T(9)) if a[0] == "head" and "pan" in a[1]]
    assert pans == [100.0]  # clamped to the neck's travel
