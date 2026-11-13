"""Hub settings: config/kaiku.toml + env overrides (KAIKU_<SECTION>_<KEY>) + .env adapter selection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from kaiku_contracts.config import find_repo_file, load_config


def repo_root() -> Path:
    cfg = find_repo_file("config/kaiku.toml")
    return cfg.parent.parent if cfg else Path.cwd()


def resolve_path(p: str | os.PathLike[str]) -> Path:
    path = Path(p)
    return path if path.is_absolute() else repo_root() / path


def _f(cfg: dict, section: str, key: str, default: float) -> float:
    try:
        return float(cfg.get(section, {}).get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    home_id: str = "demo-aino"
    language: str = "en"
    greeting_language: str = "fi"
    # adapters
    head: str = "sim"
    sensors: str = "sim"
    voice: str = "text"
    music: str = "off"
    demo_mode: bool = True
    # cloud
    cloud_url: str | None = None
    home_token: str | None = None
    uplink_batch_s: float = 2.0
    uplink_max_batch: int = 200
    uplink_timeout_s: float = 10.0
    queue_path: Path = field(default_factory=lambda: resolve_path("logs/uplink_queue.sqlite"))
    state_path: Path = field(default_factory=lambda: resolve_path("logs/hub_state.json"))
    # ritual timings (s)
    greet_s: float = 20
    dial_s: float = 45
    post_mood_s: float = 15
    breathe_s: float = 90
    breathe_bpm: float = 6
    drum_s: float = 45
    drum_idle_end_s: float = 6
    nudge_s: float = 30
    step_timeout_s: float = 120
    ritual_cooldown_s: float = 60
    hrv_window_s: float = 30
    phq9_mode: str = "laptop"  # laptop | spoken | both
    phq9_every_days: float = 14
    # perception
    presence_near_cm: float = 80
    first_of_day_after_h: float = 4
    tap_refractory_ms: float = 80
    tap_force_max_g: float = 4.0
    ppg_band_hz: tuple[float, float] = (0.7, 3.5)
    ppg_min_clean_ratio: float = 0.7
    light_window_min: float = 60
    # music
    bpm_min: float = 60
    bpm_max: float = 200
    # models (VERIFY in docs; never hard-code in code)
    gemini_live_model: str = ""
    lyria_model: str = ""
    # attention ladder ([attention]; AttentionConfig picks the keys it knows)
    attention: dict = field(default_factory=dict)
    face_source: str = "laptop"  # laptop | unoq_yolo | off
    voice_name: str = ""
    local_tts: bool = False  # KAIKU_LOCAL_TTS=1: speak scripted lines locally (and play cloud audio) in text mode
    voice_timeout_s: float = 3.0
    # safety
    helpline_name: str = "MIELI Crisis Helpline"
    helpline_number: str = "09 2525 0111"
    emergency_number: str = "112"

    @classmethod
    def load(cls) -> Settings:
        load_config.cache_clear()
        c = load_config()
        env = os.environ
        band = c.get("perception", {}).get("ppg_band_hz", [0.7, 3.5])
        return cls(
            home_id=env.get("KAIKU_HOME_ID") or c.get("home", {}).get("id", "demo-aino"),
            language=c.get("home", {}).get("language", "en"),
            greeting_language=c.get("home", {}).get("greeting_language", "fi"),
            head=env.get("KAIKU_HEAD", "sim"),
            sensors=env.get("KAIKU_SENSORS", "sim"),
            voice=env.get("KAIKU_VOICE", "text"),
            music=env.get("KAIKU_MUSIC", "off"),
            demo_mode=env.get("KAIKU_DEMO_MODE", "1") not in ("0", "false", ""),
            cloud_url=(env.get("KAIKU_CLOUD_URL") or "").rstrip("/") or None,
            home_token=env.get("KAIKU_HOME_TOKEN") or None,
            uplink_batch_s=_f(c, "uplink", "batch_s", 2),
            uplink_max_batch=int(_f(c, "uplink", "max_batch", 200)),
            uplink_timeout_s=_f(c, "uplink", "timeout_s", 10),
            queue_path=resolve_path(c.get("uplink", {}).get("queue_path", "logs/uplink_queue.sqlite")),
            state_path=resolve_path(env.get("KAIKU_HUB_STATE_PATH", "logs/hub_state.json")),
            greet_s=_f(c, "ritual", "greet_s", 20),
            dial_s=_f(c, "ritual", "dial_s", 45),
            post_mood_s=_f(c, "ritual", "post_mood_s", 15),
            breathe_s=_f(c, "ritual", "breathe_s", 90),
            breathe_bpm=_f(c, "ritual", "breathe_bpm", 6),
            drum_s=_f(c, "ritual", "drum_s", 45),
            drum_idle_end_s=_f(c, "ritual", "drum_idle_end_s", 6),
            nudge_s=_f(c, "ritual", "nudge_s", 30),
            step_timeout_s=_f(c, "ritual", "step_timeout_s", 120),
            ritual_cooldown_s=_f(c, "ritual", "cooldown_s", 60),
            hrv_window_s=_f(c, "ritual", "hrv_window_s", 30),
            phq9_mode=str(c.get("ritual", {}).get("phq9_mode", "laptop")),
            phq9_every_days=_f(c, "ritual", "phq9_every_days", 14),
            presence_near_cm=_f(c, "perception", "presence_near_cm", 80),
            first_of_day_after_h=_f(c, "perception", "presence_first_of_day_after_h", 4),
            tap_refractory_ms=_f(c, "perception", "tap_refractory_ms", 80),
            tap_force_max_g=_f(c, "perception", "tap_force_max_g", 4.0),
            ppg_band_hz=(float(band[0]), float(band[1])),
            ppg_min_clean_ratio=_f(c, "perception", "ppg_min_clean_ratio", 0.7),
            light_window_min=_f(c, "perception", "light_window_min", 60),
            bpm_min=_f(c, "music", "bpm_min", 60),
            bpm_max=_f(c, "music", "bpm_max", 200),
            gemini_live_model=str(c.get("models", {}).get("gemini_live", "")),
            lyria_model=str(c.get("models", {}).get("lyria_realtime", "")),
            attention=dict(c.get("attention", {})),
            face_source=str(c.get("attention", {}).get("face_source", "laptop")),
            voice_name=str(c.get("voice", {}).get("name", "")),
            local_tts=env.get("KAIKU_LOCAL_TTS", "0") == "1",
            voice_timeout_s=_f(c, "attention", "voice_timeout_s", 3.0),
            helpline_name=c.get("safety", {}).get("helpline_name", "MIELI Crisis Helpline"),
            helpline_number=c.get("safety", {}).get("helpline_number", "09 2525 0111"),
            emergency_number=c.get("safety", {}).get("emergency_number", "112"),
        )


def model_id_ok(model_id: str) -> bool:
    """Model IDs in config start as VERIFY-... placeholders until someone checks the docs."""
    return bool(model_id) and not model_id.upper().startswith("VERIFY")
