"""The cloud `agree_activity` tool on the robot (D50): declared for the Live session from the shared registry and
forwarded like every cloud tool, so a yes said to the robot is on the phone and the Mac at once."""

import asyncio
import json

import httpx
from kaiku_contracts.companion_tools import TOOLS as REGISTRY
from kaiku_hub.live.base import OffMusic, Voice
from kaiku_hub.live.gemini_live import live_config, non_blocking_names
from kaiku_hub.live.tools import TOOLS
from kaiku_hub.main import BACKGROUND_TOOLS, CLOUD_TOOLS, Hub

ARGS = {"kind": "walk", "said": "Yes, a walk after lunch sounds good.", "when": "later"}
KEPT = {"agreed": True, "id": "0199-a", "kind": "walk", "name": "a walk", "when": "later", "on": ["iphone"],
        "where": "your phone", "already": False, "listening": ["iphone"]}


class RecVoice(Voice):
    name = "rec"

    def __init__(self):
        self.said, self.verbatim = [], []

    async def say(self, text):
        self.said.append(text)

    async def say_verbatim(self, text):
        self.verbatim.append(text)


def make_hub(settings, seen, answer):
    def handler(request):
        if request.url.path == "/v1/companion/tool":
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"name": "agree_activity", "executor": "cloud", "error": None,
                                             "crisis": False, "result": {}} | answer)
        return httpx.Response(503)

    settings.cloud_url = "http://cloud"
    return Hub(settings, voice=RecVoice(), music=OffMusic(), transport=httpx.MockTransport(handler), read_stdin=False)


def test_the_robots_live_session_declares_it_from_the_shared_registry_as_a_blocking_tool():
    (decl,) = [t for t in TOOLS if t["name"] == "agree_activity"]
    assert decl["parameters"] is REGISTRY["agree_activity"]["parameters"] and "behavior" not in decl
    assert decl["description"] == REGISTRY["agree_activity"]["description"]
    assert "agree_activity" in CLOUD_TOOLS and "agree_activity" not in BACKGROUND_TOOLS  # Kaiku waits for the answer
    cfg = live_config("sys", TOOLS, "Sulafat")
    names = [d["name"] for d in cfg["tools"][0]["function_declarations"]]
    assert "agree_activity" in names and non_blocking_names(cfg["tools"]) == {"feel"}
    from google.genai import types

    sdk = types.LiveConnectConfig(**cfg)  # accepted by the installed SDK as it is sent
    assert next(d for d in sdk.tools[0].function_declarations if d.name == "agree_activity").behavior is None


async def test_a_yes_to_the_robot_is_forwarded_and_the_model_hears_where_it_is(settings):
    seen = []
    hub = make_hub(settings, seen, {"ok": True, "result": KEPT})
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    out = await hub.on_tool("agree_activity", ARGS)
    assert out == {"ok": True, **KEPT} and out["where"] == "your phone"  # what Kaiku can truthfully say
    (call,) = seen
    assert (call["name"], call["surface"], call["args"]) == ("agree_activity", "robot", ARGS)
    assert call["home_id"] == settings.home_id and "agree_activity" in hub._episode["tools_used"]
    assert hub.machine.running  # nothing about the ritual changes: the robot has no screen to open
    await hub.end_ritual()


async def test_a_refusal_reaches_the_model_as_the_reason_and_a_dead_cloud_as_unavailable(settings):
    why = "Not kept: those words are not a clear yes. Do not say it is on any device."
    seen = []
    hub = make_hub(settings, seen, {"ok": False, "error": why, "result": {"agreed": False, "reason": "not_a_yes"}})
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    out = await hub.on_tool("agree_activity", {"kind": "walk", "said": "maybe"})
    assert out == {"ok": False, "agreed": False, "reason": "not_a_yes", "error": why}

    def down(request):
        raise httpx.ConnectError("down")

    hub.cloud.transport = httpx.MockTransport(down)
    assert await hub.on_tool("agree_activity", ARGS) == {"ok": False, "error": "not available right now"}
    await hub.end_ritual()


async def test_the_clouds_crisis_answer_runs_the_robots_crisis_path(settings):
    seen = []
    hub = make_hub(settings, seen, {"ok": False, "crisis": True, "error": "crisis", "result": {"stop_session": True}})
    hub.start_ritual("test")
    await asyncio.sleep(0.05)
    out = await hub.on_tool("agree_activity", ARGS)
    assert out == {"ok": False, "error": "stopped"} and len(seen) == 1
    assert not hub.machine.running and hub.voice.verbatim
    assert [e.type for e in hub.emitted].count("obs.safety_flag") == 1
