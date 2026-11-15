"""Deterministic explanation (no LLM). Always available; the fallback for every other backend."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kaiku_contracts.api import Explanation, SourceNote
from kaiku_contracts.config import get
from kaiku_contracts.sources import SOURCE_LABELS

CAVEATS = ("Change signals are measured against this person's own recent baseline; they are not clinical "
           "findings and can have ordinary causes. Source groups combine related "
           "inputs; a group label does not confirm that a physical device is connected.")
SOURCE_LABEL = SOURCE_LABELS  # robot "Home robot", glasses, laptop "Apps", wearable "Watch"
VERDICT_WORD = {"better": "better than usual", "as_usual": "as usual", "worse": "worse than usual",
                "insufficient": "not enough data"}


def source_line(v: dict[str, Any]) -> str:
    word = VERDICT_WORD[v["verdict"]]
    ev = [e["summary"][0].lower() + e["summary"][1:] for e in v.get("evidence", [])[:2] if e.get("summary")]
    return f"{word} — {'; '.join(ev)}" if ev and v["verdict"] in ("worse", "better") else word


def template_explanation(ctx: dict[str, Any]) -> Explanation:
    """ctx: {display_name, state, agreement, sources: [SourceVerdict dicts], notes: [...]}"""
    name = ctx["display_name"]
    state = ctx["state"]
    sources = ctx["sources"]
    worse = [v for v in sources if v["verdict"] == "worse"]
    per = [SourceNote(source=v["source"], summary=f"{SOURCE_LABEL[v['source']]}: {source_line(v)}.") for v in sources]
    sufficient = [v for v in sources if v["verdict"] != "insufficient"]
    if state == "safety":
        headline = f"{name}: safety trigger — contact today"
        # "was shown" only when the flag itself says the device handled it (payload `handled_locally`)
        helpline, emergency = get("safety", "helpline_name", ""), get("safety", "emergency_number", "")
        shown = (f"The person was shown the {helpline} and {emergency} on the spot. "
                 if ctx.get("safety_handled_locally") and helpline and emergency
                 else "The flag does not record that the person was shown crisis contacts on their device. ")
        text = ("A crisis trigger was raised (PHQ-9 item 9, crisis language or the manual button). "
                f"{shown}Please contact them today.")
        actions = ["check_in_call", "send_message"]
    elif state == "needs_call":
        labels = [SOURCE_LABEL[v["source"]].lower() for v in worse]
        ack = "A clinician has acknowledged it. " if ctx.get("acknowledged") else ""
        if labels:
            names = (", ".join(labels[:-1]) + " and " + labels[-1]) if len(labels) > 1 else labels[0]
            verb = "show" if len(labels) > 1 or names.endswith("s") else "shows"
            headline = f"{name}: {names} {verb} change from their usual — needs a call"
            count = "One source group reports" if len(worse) == 1 else f"{len(worse)} source groups report"
            text = (f"{count} worse than this person's usual. {ack}"
                    "Worth a check-in call. What follows from it is the care team's decision.")
        else:  # held from an earlier day (consensus hysteresis): nothing is away from usual today
            headline = f"{name}: held from an earlier change — needs a call"
            text = ("No source group reports worse than usual today. The state is held from an earlier change until "
                    f"enough as-usual days have passed or the care team acknowledges it. {ack}"
                    "Worth a check-in call. What follows from it is the care team's decision.")
        actions = ["check_in_call", "send_message"]
    elif state == "watch":
        if len(sufficient) < 2:
            headline = f"{name}: too little data from enough sources — watching"
            text = (f"Only {len(sufficient)} source has enough recent data, so the consensus can't confirm a stable "
                    "picture. Encourage the missing sessions or walks.")
        elif not worse:  # nothing away from usual: a young record, or a day still settling
            forming = ctx["agreement"] == "low_coverage"
            headline = (f"{name}: baseline still forming — watching" if forming
                        else f"{name}: no change from their usual — watching")
            text = ("No source group reports worse than usual. "
                    + ("This person's own baseline is still forming, so the consensus stays on watch." if forming
                       else "The consensus stays on watch for now."))
        else:
            src = SOURCE_LABEL[worse[0]["source"]].lower()
            verb = "show" if src.endswith("s") else "shows"
            headline = f"{name}: {src} {verb} change from their usual — watching"
            count = "One source group reports" if len(worse) == 1 else f"{len(worse)} source groups report"
            text = f"{count} worse than usual. Not enough on its own for a call."
        actions = ["none"]
    else:
        headline = f"{name}: consensus stable — as usual"
        text = "The sources with enough data report as usual or better than this person's own baseline."
        actions = ["none"]
    disagreement = None
    if ctx["agreement"] == "disagree":
        disagreement = "; ".join(f"{SOURCE_LABEL[v['source']].lower()}: {VERDICT_WORD[v['verdict']]}"
                                 for v in sources if v["verdict"] != "insufficient")
        disagreement = f"Sources disagree ({disagreement})."
    caveats = CAVEATS
    if "correlated_only" in ctx.get("notes", []):
        fams = ", ".join(f.replace("_", "-") for f in ctx.get("correlated_families", [])) or "correlated measures"
        caveats = (f"The only worse signals are {fams} measures (e.g. dial and PHQ-9), which are not independent of "
                   "each other. " + caveats)
    low = [SOURCE_LABEL[v["source"]] for v in sources if v["verdict"] == "insufficient"]
    if low:
        caveats += f" Not enough recent data from: {', '.join(low)}."
    return Explanation(headline=headline[:200], text=text[:1200], per_source=per,
                       disagreement_note=disagreement[:400] if disagreement else None, suggested_actions=actions,
                       caveats=caveats[:600], by="template", model=None, generated_at=datetime.now(UTC))
