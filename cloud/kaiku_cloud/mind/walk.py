"""Walking together: the style Kaiku walks in, the nudges the device sends, and what the walk card carries.

A Live session only answers input. So that Kaiku can speak when something worth it comes into view (or after a
quiet stretch, in the styles that do that), the device sends a short context line on a timer and Kaiku answers it
only when it has something to say: `CompanionSessionResponse.walk` (`WalkGuide`) carries the intervals and the
lines, all from config/kaiku.toml [walk]. What each style is: config/persona.md "Walking together"; its word limits
and rules: config/surfaces.toml `[surface.glasses.styles.*]`.

D43 holds: pictures go only from the phone to the Live conversation. Nothing here sees, stores or derives anything
from a frame. What the walk card carries (`outdoor_likes`) is only what the person told Kaiku and let it keep.
"""

from __future__ import annotations

import re

from kaiku_contracts.api import WalkGuide
from kaiku_contracts.companion_tools import WALK_STYLES
from kaiku_contracts.config import load_config

from ..store.db import Store

# A liked thing counts as an outdoor one when it names something a walk can pass. Places always count.
OUTDOOR = re.compile(r"\b(?:trees?|lake|park|forest|woods?|bench|path|trail|loop|garden|river|sea|shore|beach|pond|"
                     r"birds?|ducks?|swans?|squirrels?|dogs?|flowers?|blossom|sky|sunset|sunrise|bridge|hill|rocks?|"
                     r"field|meadow|market|harbour|harbor|snow|walk\w*)\b", re.I)


def is_walk(purpose: str | None, intent: str) -> bool:
    return purpose == "walk" or (purpose is None and intent == "walk")


def style_of(requested: str | None) -> str:
    style = requested or str(load_config().get("walk", {}).get("default_style", "quiet"))
    return style if style in WALK_STYLES else "quiet"


def guide(style: str) -> WalkGuide:
    cfg = load_config().get("walk", {}).get(style, {})
    look, quiet = int(cfg.get("look_every_s") or 0), int(cfg.get("quiet_after_s") or 0)
    return WalkGuide(style=style,  # type: ignore[arg-type]
                     look_every_s=look or None, look_prompt=(cfg.get("look_prompt") or None) if look else None,
                     quiet_after_s=quiet or None, quiet_prompt=(cfg.get("quiet_prompt") or None) if quiet else None)


def outdoor_likes(store: Store, home_id: str) -> list[str]:
    """Places and outdoor likes from the notebook, in the person's words, newest first."""
    limit = int(load_config().get("walk", {}).get("outdoor_likes", 4))
    mems = store.memories(home_id)
    mine = [m for m in mems  # the store lists them newest first
            if m["category"] == "places" or (m["category"] == "likes" and OUTDOOR.search(m["text"]))]
    return [m["text"] for m in mine[:limit]]
