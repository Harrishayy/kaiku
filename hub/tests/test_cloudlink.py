import httpx
from kaiku_contracts import example, to_json
from kaiku_hub.cloudlink import CloudLink, local_nudge


async def test_commands_repeat_until_ack_and_never_advance_since():
    cmd = example("cmd.hub", home_id="demo-aino", source="cloud")
    other_home = example("cmd.hub", home_id="someone-else", source="cloud")
    seen_params = []

    def handler(req: httpx.Request):
        seen_params.append(dict(req.url.params))
        import json

        return httpx.Response(200, json={"commands": [json.loads(to_json(cmd)), json.loads(to_json(other_home))]})

    cl = CloudLink(url="http://cloud", home_id="demo-aino", transport=httpx.MockTransport(handler))
    first = await cl.poll_commands()
    second = await cl.poll_commands()
    assert [str(e.id) for e in first] == [str(cmd.id)]
    assert [str(e.id) for e in second] == [str(cmd.id)]
    assert "since" not in seen_params[1]


async def test_nudge_fallback_offline():
    def down(req):
        raise httpx.ConnectError("x")

    cl = CloudLink(url="http://cloud", home_id="demo-aino", transport=httpx.MockTransport(down))
    assert await cl.get_nudge() is None
    assert await CloudLink(url=None, home_id="h").get_nudge() is None
    assert local_nudge("friend_ping")[0] == "friend_ping"
    assert local_nudge()[0] in {"breathe", "drum", "daylight_walk", "friend_ping", "icbt_exercise"}


async def test_nudge_and_health_ok():
    got = {}

    def handler(req: httpx.Request):
        if req.url.path == "/v1/nudge":
            return httpx.Response(200, json={"arm": "drum", "reason": "Drumming lifted you twice.", "probs": {}})
        got["health"] = req.content
        return httpx.Response(204)

    cl = CloudLink(url="http://cloud", home_id="demo-aino", transport=httpx.MockTransport(handler))
    assert (await cl.get_nudge()).arm == "drum"
    hb = example("health").payload.model_dump(mode="json")
    assert await cl.report_health({"head": hb}, 3, 1.5) is True
    assert b'"uplink_queue":3' in got["health"].replace(b" ", b"")
