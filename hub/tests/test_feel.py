"""The cloud `feel` tool on the robot: declared for the Live session, no thinking pose, crisis gate first."""

import asyncio
import json

import httpx
import pytest
from kaiku_contracts.companion_tools import TOOLS as REGISTRY
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.live.gemini_live import live_config, non_blocking_names, tool_config
from kaiku_hub.live.tools import TOOLS
from kaiku_hub.main import BACKGROUND_TOOLS, Hub

FEEL = {"kind": "sad_news", "heard": {"valence": "low", "tone": ["tearful"], "via": "voice"},
        "about": "my cat", "said": "my cat died last night"}
PLAN = {"stance": "comfort", "depth": "stay", "reflect_hint": "Give back the thing in their words.",
        "recall": None, "may_offer": None, "follow_up_saved": True, "scheduling": "WHEN_IDLE"}


class RecVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said, self.verbatim = [], []

    async def say(self, text):
        self.said.append(text)

    async def say_verbatim(self, text):
        self.verbatim.append(text)


def make_hub(settings, handler):
    settings.cloud_url = "http://cloud"
    hub = Hub(settings, voice=RecVoice(), music=OffMusic(), transport=httpx.MockTransport(handler), read_stdin=False)
    hub.heads = []
    real = hub._cmd

    async def cmd(type_, payload, **kw):
        if type_ == "cmd.head":
            hub.heads.append(dict(payload))
        await real(type_, payload, **kw)

    hub._cmd = cmd
    return hub


def tool_handler(seen, result=PLAN, **extra):
    def handler(request):
        if request.url.path == "/v1/companion/tool":
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "name": "feel", "executor": "cloud", "result": result,
                                             "error": None, "crisis": False, **extra})
        return httpx.Response(503)
    return handler


# ---------------------------------------------------------------- (2) the robot's Live session offers it
def test_feel_is_declared_from_the_shared_registry_and_non_blocking():
    (feel,) = [t for t in TOOLS if t["name"] == "feel"]
    assert feel["behavior"] == "NON_BLOCKING" and feel["parameters"] is REGISTRY["feel"]["parameters"]
    assert feel["description"] == REGISTRY["feel"]["description"] and BACKGROUND_TOOLS == {"feel"}
    cfg = live_config("sys", TOOLS, "Sulafat")
    decl = next(d for d in cfg["tools"][0]["function_declarations"] if d["name"] == "feel")
    assert decl["behavior"] == "NON_BLOCKING" and non_blocking_names(cfg["tools"]) == {"feel"}
    types = pytest.importorskip("google.genai.types")
    sdk = types.LiveConnectConfig(**cfg)                       # the installed SDK accepts the declaration
    assert next(d for d in sdk.tools[0].function_declarations if d.name == "feel").behavior == types.Behavior.NON_BLOCKING


def test_backend_without_asynchronous_calls_gets_a_plain_blocking_declaration():
    blocking = tool_config(TOOLS, non_blocking=False)
    assert all("behavior" not in d for d in blocking[0]["function_declarations"]) and non_blocking_names(blocking) == set()
    assert any(d["name"] == "feel" for d in blocking[0]["function_declarations"])   # still offered, just blocking
    blocks = [{"function_declarations": [{"name": "feel", "behavior": "NON_BLOCKING"}]}]
    assert tool_config(blocks) == blocks
    assert tool_config(blocks, non_blocking=False) == [{"function_declarations": [{"name": "feel"}]}]


# ---------------------------------------------------------------- (1) no thinking pose, the plan comes back
async def test_feel_keeps_listening_no_thinking_eyes_no_glance(settings):
    seen, during = [], []
    hub = make_hub(settings, None)

    def handler(request):
        during.append((hub.thinking, list(hub.heads)))        # the body while the call is in flight
        return tool_handler(seen)(request)

    hub.cloud.transport = hub.uplink.transport = httpx.MockTransport(handler)
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    before = list(hub.heads)
    out = await hub.on_tool("feel", FEEL)
    assert out == {"ok": True, **PLAN} and out["scheduling"] == "WHEN_IDLE"
    assert seen[0]["name"] == "feel" and seen[0]["surface"] == "robot" and seen[0]["args"] == FEEL
    tool_calls = [d for d in during if d[1] == before]
    assert tool_calls and all(t == 0 for t, _h in tool_calls)  # never "thinking" while feel runs
    assert hub.heads == before                                 # not one cmd.head: no thinking eyes, no glance up
    assert not any(h.get("eyes") == "thinking" or "look" in h for h in hub.heads[len(before):])
    assert hub.voice.said.count("Let me think about that later.") == 0
    assert "feel" in hub._episode["tools_used"]
    await hub.on_tool("recall", {"topic": "cat"})              # an ordinary cloud tool still shows the thinking body
    assert any(h.get("eyes") == "thinking" for h in hub.heads[len(before):])
    await hub.end_ritual()


async def test_feel_unavailable_or_slow_is_silent_never_a_spoken_line(settings):
    def down(request):
        raise httpx.ConnectError("down")

    hub = make_hub(settings, down)
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    assert await hub.on_tool("feel", FEEL) == {"ok": False, "error": "not available right now", "scheduling": "SILENT"}

    async def slow(*a, **k):
        await asyncio.sleep(1)

    hub.cloud.companion_tool = slow
    hub.think_timeout_s = 0.05
    out = await hub.on_tool("feel", FEEL)
    await asyncio.sleep(0.05)
    assert out["ok"] is False and out["scheduling"] == "SILENT" and hub.thinking == 0
    assert "Let me think about that later." not in hub.voice.said and hub.machine.running
    bad = await hub.on_tool("feel", {"kind": "sad_news"})      # schema problem: refused locally, nothing forwarded
    assert bad["ok"] is False and "missing heard" in bad["error"] and bad["scheduling"] == "SILENT"
    await hub.end_ritual()
    assert (await hub.on_tool("feel", FEEL))["error"] == "no active consented conversation"


# ---------------------------------------------------------------- (3) the crisis gate stays first
async def test_crisis_words_in_feel_arguments_never_reach_the_cloud(settings):
    seen = []
    hub = make_hub(settings, tool_handler(seen))
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    out = await hub.on_tool("feel", {**FEEL, "said": "honestly I want to die"})
    assert out == {"ok": False, "error": "stopped", "scheduling": "SILENT"}
    assert seen == []                                          # the local gate ran before anything was forwarded
    assert not hub.machine.running and hub.voice.verbatim
    assert [e.type for e in hub.emitted].count("obs.safety_flag") == 1
    assert hub.heads[-2]["eyes"] == "soft" and hub.heads[-1] == {"show": "help"}   # calm, then the help screen


async def test_cloud_gate_on_feel_also_runs_the_crisis_path(settings):
    seen = []
    hub = make_hub(settings, tool_handler(seen, result=None, crisis=True))
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    out = await hub.on_tool("feel", FEEL)
    assert out["ok"] is False and out["error"] == "stopped" and len(seen) == 1
    assert not hub.machine.running and [e.type for e in hub.emitted].count("obs.safety_flag") == 1
