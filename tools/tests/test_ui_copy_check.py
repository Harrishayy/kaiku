"""Build notes (config paths, obs types, make targets, TODO/VERIFY) must never reach a person's screen."""

from pathlib import Path

from tools import ui_copy_check


def test_app_copy_has_no_build_notes():
    assert ui_copy_check.scan() == []


def test_checker_catches_visible_notes_and_ignores_code(tmp_path: Path):
    app = tmp_path / "apps/web/app/x"
    app.mkdir(parents=True)
    (app / "Page.tsx").write_text(
        "// config/safety_phrases.toml is fine in a comment\n"
        "const t = 'obs.safety_flag'; post({ payload });\n"
        "<p>This text is the scripted message from config/safety_phrases.toml.</p>\n"
        '<button aria-label="TODO rename">Hi</button>\n'
    )
    found = ui_copy_check.scan(tmp_path)
    lines = {f.split(": build")[0].rsplit(":", 1)[1] for f in found}
    assert lines == {"3", "4"}, found
