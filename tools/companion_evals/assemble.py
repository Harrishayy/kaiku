"""System-instruction assembly for the evals. Ground truth: `kaiku_cloud.mind.assemble` (what the cloud serves on
`POST /v1/companion/session`), re-exported here so the evals test exactly that code."""

from kaiku_cloud.mind.assemble import (  # noqa: F401
    CARD_KEYS,
    ROOT,
    TONE_TEXT,
    assemble,
    hashlib,
    load_files,
    parse_persona,
    parse_surfaces,
    persona_version,
    render_card,
    render_surface,
    styled,
    validate_card,
)
