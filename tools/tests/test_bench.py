"""Bench checker: every part definition loads, and saved monitor logs pass/fail as they should."""

from pathlib import Path

import pytest

from tools import bench

FIX = Path(__file__).parent / "fixtures" / "bench"
YES = lambda _q: True  # noqa: E731
NO = lambda _q: False  # noqa: E731


def _run(part_dir: str, log: str, answer=YES) -> dict[str, bool]:
    part = bench.Part.load(bench.ROOT / part_dir)
    lines = list(bench.parse_lines((FIX / log).read_text().splitlines()))
    return {c.name: ok for c, ok, _ in bench.evaluate(part, lines, answer)}


def test_every_part_loads_and_covers_every_sensor():
    parts = {p.part: p for p in bench.discover()}
    # one bench per physical part on both boards, plus a whole-node link check each
    assert {"knock", "ky039", "hall", "light", "buzzer", "camera", "unoq-link",
            "button", "knob", "display", "leds", "motor", "speaker", "mic", "head-link"} <= set(parts)
    for p in parts.values():
        assert p.steps and p.flash and p.checks


def test_knock_pass_and_bounce_fail():
    assert all(_run("firmware/unoq-sensors/bench/knock", "knock_pass.log").values())
    res = _run("firmware/unoq-sensors/bench/knock", "knock_bounce.log")
    assert res["exactly 5 knocks (no bounce doubles, no misses)"] is False


def test_ky039_pass_and_flat_fail():
    assert all(_run("firmware/unoq-sensors/bench/ky039", "ky039_pass.log").values())
    res = _run("firmware/unoq-sensors/bench/ky039", "ky039_flat.log")
    assert res["samples at a stable 100 Hz"] is True
    assert res["a real signal (not flat, not pinned at the rail)"] is False


def test_ask_checks_use_the_answer():
    res = _run("firmware/unoq-sensors/bench/buzzer", "knock_pass.log", answer=NO)
    assert res["heard"] is False and res["Modulino Buzzer answers on Wire1 at 0x3C"] is False


def test_parse_lines_skips_noise_and_non_events():
    out = list(bench.parse_lines(["boot banner", 'I (123) {"event":"x","a":1}', '{"no_event":1}', "{bad json"]))
    assert out == [{"event": "x", "a": 1}]


def test_source_filter_for_mqtt_lines():
    c = bench.Check(name="h", event="health", source="head", min_count=1)
    assert c.evaluate([{"event": "health", "source": "hub"}], YES)[0] is False
    assert c.evaluate([{"event": "health", "source": "head"}], YES)[0] is True


def test_cli_on_a_log_file(capsys):
    rc = bench.main(["firmware/unoq-sensors/bench/knock", "--from", str(FIX / "knock_pass.log")])
    assert rc == 0 and "PASS" in capsys.readouterr().err


def test_bad_part_definition(tmp_path):
    (tmp_path / "bench.toml").write_text('part="x"\nboard="toaster"\nprogram="p"\nflash="f"\nsteps=[]\n'
                                         '[[check]]\nname="c"\nevent="e"\n')
    with pytest.raises(ValueError, match="board"):
        bench.Part.load(tmp_path)
