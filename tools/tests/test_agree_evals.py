"""Companion evals for an activity agreed in one place (scenarios/agree.yaml, D50): the tool is called once on a
clear yes with the person's own words, never on a maybe, and nothing is said to be on a device without a result."""

from tools.companion_evals import assemble, run, safety, tool_specs

PERSONA, SURFACES = assemble.load_files()
SCENARIOS = {s["id"]: s for s in run.load_scenarios() if s["file"] == "agree.yaml"}
YES, MAYBE, GAME = "robot-agree-walk-after-low-dial", "robot-agree-maybe-is-not-a-yes", "glasses-agree-game-for-when-they-are-home"


def dry(scn_id, replies=None):
    """Evaluate one scenario against its own fixture, or against `replies` (a bad variant)."""
    scn = SCENARIOS[scn_id]
    fixture = {scn_id: replies} if replies is not None else run.load_dry_replies()
    surface = assemble.styled(SURFACES, scn["surface"], scn.get("context", {}).get("walk_style"))
    transcript = run.run_dry_scenario(scn, fixture, safety.SafetyCheck.from_file())
    return run.evaluate(scn, transcript, surface, tool_specs.load()), transcript


def agree_calls(transcript):
    return [c for t in transcript if t["role"] == "kaiku" for c in t.get("tools", []) if c["name"] == "agree_activity"]


def test_the_scenarios_pass_on_their_fixtures_and_the_prompt_carries_the_rule():
    assert set(SCENARIOS) == {YES, MAYBE, GAME}
    for scn_id, scn in SCENARIOS.items():
        issues, _ = dry(scn_id)
        assert issues == [], (scn_id, issues)
        prompt = assemble.assemble(PERSONA, SURFACES, scn["surface"], scn["context"] | {"language": "en"})
        assert "`agree_activity`: when they clearly say yes" in prompt and "is not a yes" in prompt, scn_id
        assert "`agree_activity`: only after a clear yes" in prompt  # the persona's own line under "Tools"


def test_a_clear_yes_on_the_robot_is_one_call_with_their_words_and_the_cloud_rule_keeps_it():
    scn = SCENARIOS[YES]
    _, transcript = dry(YES)
    (call,) = agree_calls(transcript)
    assert call["args"]["kind"] == "walk" and call["args"]["said"] == scn["turns"][2]  # the person's own words
    assert call["result"]["agreed"] and call["result"]["on"] == ["iphone"] and call["result"]["where"] == "your phone"
    replies = run.load_dry_replies()[YES]
    assert "walk" in replies[1]["say"] and "phone" in replies[2]["say"]  # offered first, then said where it is
    # the offer came from the person's record and this body cannot start it: the fake mind says where it can go
    feel = next(c for t in transcript if t["role"] == "kaiku" for c in t.get("tools", []) if c["name"] == "feel")
    plan = run._sim_tool_result("feel", feel["args"], scn["context"], scn["mind"], {})
    assert plan.get("offer_elsewhere") == "walk" and "offer_activity" not in plan


def test_a_maybe_is_not_a_yes_and_calling_the_tool_on_it_fails_the_scenario():
    issues, transcript = dry(MAYBE)
    assert issues == [] and agree_calls(transcript) == []
    replies = [dict(r) for r in run.load_dry_replies()[MAYBE]]
    maybe = SCENARIOS[MAYBE]["turns"][2]
    replies[2] = {"say": "Lovely. It's on your phone.",
                  "tools": [{"name": "agree_activity", "args": {"kind": "walk", "said": maybe}}]}
    issues, transcript = dry(MAYBE, replies)
    assert {"forbidden_tool:agree_activity", "agree:calls:1", "agree:claimed_without_result"} <= set(issues)
    (call,) = agree_calls(transcript)  # and the cloud's own rule would not have kept it either
    assert call["result"]["agreed"] is False and call["result"]["reason"] == "not_a_yes"


def test_each_way_of_getting_the_yes_wrong_is_caught():
    good = run.load_dry_replies()[YES]
    kept = good[2]["tools"][0]

    def variant(third):
        return dry(YES, [good[0], good[1], third])[0]

    assert "agree:calls:0" in variant({"say": "A walk after lunch, then."})  # heard the yes, kept nothing
    assert "agree:claimed_without_result" in variant({"say": "A walk after lunch. It's on your phone."})  # said so anyway
    assert "agree:did_not_say_where" in variant({"say": "A walk after lunch, then.", "tools": [kept]})
    twice = variant({"say": "It's on your phone.", "tools": [kept, kept]})
    assert "agree:calls:2" in twice
    not_theirs = {**kept, "args": {**kept["args"], "said": "Yes please, I would love a long walk"}}
    assert "agree:not_their_words" in variant({"say": "It's on your phone.", "tools": [not_theirs]})
    wrong_kind = {**kept, "args": {**kept["args"], "kind": "lantern"}}
    assert "agree:kind:lantern" in variant({"say": "It's on your phone.", "tools": [wrong_kind]})
    # called before any offer and before the yes
    early = dry(YES, [{"say": "A heavy morning. It's on your phone.", "tools": [
        {"name": "agree_activity", "args": {"kind": "walk", "said": "Two. It's a heavy one this morning."}}]}, good[1],
        {"say": "A walk after lunch, then."}])[0]
    assert {"agree:on_turn:1", "agree:no_offer_before", "agree:claimed_without_result"} <= set(early)


def test_a_game_asked_for_on_a_walk_goes_to_the_phone_and_the_mac_not_to_a_screen_they_are_told_to_look_at():
    _, transcript = dry(GAME)
    (call,) = agree_calls(transcript)
    assert call["args"]["kind"] == "lantern" and call["result"]["where"] == "your phone and your Mac"
    assert call["result"]["on"] == ["iphone", "mac"]
    bad = dry(GAME, [run.load_dry_replies()[GAME][0], {"say": "Sure. Check your phone, it's there.", "tools": [call]}])[0]
    assert any(i.startswith("surface_rule") for i in bad)  # a walk never sends them to a screen


def test_the_fake_backend_runs_the_clouds_rule():
    card = {"tone": "steady"}
    state: dict = {}
    first = run._sim_tool_result("agree_activity", {"kind": "walk", "said": "Yes, okay."}, card, {}, state)
    again = run._sim_tool_result("agree_activity", {"kind": "walk", "said": "Yes!"}, card, {}, state)
    assert first["agreed"] and not first["already"] and again["already"]
    refused = {
        "no_words": ({"kind": "walk"}, card, {}),
        "not_a_yes": ({"kind": "walk", "said": "we'll see"}, card, {}),
        "no_screen": ({"kind": "walk", "said": "yes"}, card, {"screens": ["mac"]}),
        "gentle_day": ({"kind": "walk", "said": "yes"}, {"tone": "extra-gentle"}, {}),
    }
    for reason, (args, c, mind) in refused.items():
        out = run._sim_tool_result("agree_activity", args, c, mind, {})
        assert (out["ok"], out["agreed"], out["reason"]) == (False, False, reason) and "Not kept" in out["error"]
