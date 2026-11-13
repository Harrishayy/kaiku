"""Deterministic explanation (no LLM). Always available; the fallback for every other backend."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kaiku_contracts.api import Explanation, SourceNote
from kaiku_contracts.sources import SOURCE_LABELS

CAVEATS = ("Change signals are measured against this person's own recent baseline; they are not clinical "
           "findings and can have ordinary causes. Simulated data is labelled SIMULATED.")
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
        text = ("A crisis trigger was raised (PHQ-9 item 9, crisis language or the manual button). The person was "
                "shown the MIELI Crisis Helpline and 112 on the spot. Please contact them today.")
        actions = ["check_in_call", "send_message"]
    elif state == "needs_call":
        labels = [SOURCE_LABEL[v["source"]].lower() for v in worse]
        names = (", ".join(labels[:-1]) + " and " + labels[-1]) if len(labels) > 1 else (labels[0] if labels
                                                                                          else "two sources")
        headline = f"{name}: {names} show change from their usual — needs a call"
        text = (f"{len(worse)} independent sources report worse than this person's usual. "
                + ("A clinician acknowledged it; the state holds until three stable days. " if ctx.get("acknowledged")
                   else "") + "Worth a check-in call; consider a booster or an iCBT referral.")
        actions = ["check_in_call", "flag_booster", "flag_icbt_referral"]
    elif state == "watch":
        if len(sufficient) < 2:
            headline = f"{name}: too little data from enough sources — watching"
            text = (f"Only {len(sufficient)} source has enough recent data, so the consensus can't confirm a stable "
                    "picture. Encourage the missing sessions or walks.")
        else:
            src = SOURCE_LABEL[worse[0]["source"]].lower() if worse else "one source"
            verb = "show" if src.endswith("s") else "shows"
            headline = f"{name}: {src} {verb} change from their usual — watching"
            text = "One source reports worse than usual; the others look as usual. Not enough on its own for a call."
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
