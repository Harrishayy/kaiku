import ast
from pathlib import Path

import pytest
from kaiku_hub.safety import ButtonLongPress, CrisisScript, SafetyGate, normalise

SAFETY_DIR = Path(__file__).resolve().parents[1] / "kaiku_hub" / "safety"


@pytest.fixture(scope="module")
def gate():
    return SafetyGate.from_file()


@pytest.mark.parametrize(
    "text,lang",
    [
        ("I want to die", "en"),
        ("Sometimes I think about SUICIDE.", "en"),
        ("i’m not okay", "en"),  # curly apostrophe + "okay"
        ("Im not ok", "en"),
        ("I feel like I can't go on", "en"),
        ("haluan kuolla", "fi"),
        ("En jaksa enää.", "fi"),
        ("Mietin itsemurhaa", "fi"),
        ("jag vill dö", "sv"),
        ("Jag orkar inte längre", "sv"),
    ],
)
def test_phrase_triggers(gate, text, lang):
    t = gate.check_text(text)
    assert t is not None and t.kind == "phrase" and t.language == lang


@pytest.mark.parametrize("text", ["I'm okay today", "let's drum", "four", "the drums killed it", ""])
def test_no_false_trigger(gate, text):
    assert gate.check_text(text) is None


def test_phq9_item9():
    assert SafetyGate.check_phq9(item9_score=1).kind == "phq9_item9"
    assert SafetyGate.check_phq9(item9_positive=True).kind == "phq9_item9"
    assert SafetyGate.check_phq9(item9_score=0) is None


def test_button_long_press_fires_once_while_held():
    b = ButtonLongPress(hold_s=2.0)
    assert b.update(True, 0.0) is None
    assert b.poll(1.0) is None
    assert b.poll(2.1).kind == "manual"
    assert b.poll(3.0) is None
    assert b.update(False, 3.5) is None


def test_button_short_press_is_not_crisis():
    b = ButtonLongPress()
    b.update(True, 0.0)
    assert b.was_short_press(False, 0.3)
    assert b.update(False, 0.3) is None


def test_script_is_verbatim_and_has_helplines():
    s = CrisisScript.from_file()
    for lang in ("en", "fi"):
        assert "09 2525 0111" in s.text(lang) and "112" in s.text(lang)


def test_built_in_fallback_script_and_defaults_name_the_configured_helpline():
    """The fallback script is in code so the crisis path never depends on a file. It must still say the same
    helpline as config/kaiku.toml [safety], and so must the settings' built-in defaults."""
    from kaiku_contracts.config import load_config
    from kaiku_hub.settings import Settings

    load_config.cache_clear()
    safety = load_config()["safety"]
    for key in ("helpline_name", "helpline_number", "emergency_number"):
        assert str(safety[key]) in CrisisScript.FALLBACK
        assert getattr(Settings(), key) == str(safety[key])
    assert CrisisScript({}).text("en") == CrisisScript.FALLBACK


def test_normalise():
    assert normalise("  I’M — NOT   OK!! ") == "i'm not ok"


def test_safety_never_imports_llm_or_network():
    banned = {"google", "genai", "httpx", "requests", "kaiku_hub.live", "openai", "anthropic"}
    for f in SAFETY_DIR.glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [("." * node.level) + (node.module or "")]
            for n in names:
                assert not any(n == b or n.startswith(b + ".") or n.startswith("..live") for b in banned), (f, n)
