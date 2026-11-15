"""Hub settings: config/kaiku.toml + env overrides (KAIKU_<SECTION>_<KEY>) + .env adapter selection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from kaiku_contracts.config import find_repo_file, load_config

from .perception.tap_back import TapBackConfig


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
    greeting_language: str = "en"
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
    # local session store ([hub]); None = off (the default for bare Settings(), so tests never write into logs/)
    store_path: Path | None = None
    store_retention_days: float = 30
    store_max_mb: float = 200
    engagement_enabled: bool = True
    head_mode: str = "auto"  # auto | follow | drive ([hub]; follow = the standalone head runs the ritual, D44)
    robot_home_id: str | None = None  # the home the robot boards publish on, when it is not the person's record id
    head_stale_s: float = 15.0
    talk_idle_end_s: float = 180.0  # [hub]: a talk on the robot with nothing said this long ends by itself (D64)
    follow_offer_every_s: float = 300.0  # follow mode: the spoken invitation at the head's greeting, at most this often
    trace: bool = True  # raw.hub.trace on the home broker: Kaiku's own lines and tool names, for the apps' Kaiku bot tab
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
    # robot build ([robot]): how the dial is answered and whether the head sways while drumming
    dial_input: str = "ear"  # ear | button
    press_window_s: float = 4.0  # button build: presses within this gap count as one answer
    drum_sway: bool = True  # False when the drum is a knock switch (motor vibration would trigger it)
    phq9_every_days: float = 14
    # perception
    presence_near_cm: float = 80
    first_of_day_after_h: float = 4
    presence_leave_s: float | None = None  # None = same as the 1 s arrival confirm
    presence_stale_s: float | None = None  # None = never expire a silent distance stream
    quality_min: float = 0.5
    tap_refractory_ms: float = 80
    tap_force_max_g: float = 4.0
    ppg_band_hz: tuple[float, float] = (0.7, 3.5)
    ppg_min_clean_ratio: float = 0.7
    light_enabled: bool = False
    light_window_min: float = 60
    # music
    bpm_min: float = 60
    bpm_max: float = 200
    music_out: str = "head"  # head | speaker | file ([music] out): where the drum music and its cues are heard
    head_lead_ms: float = 80  # how far ahead of real time the hub sends audio to the head's speaker
    head_gain: float = 0.8  # headroom for the head's small speaker
    phone_mic_tail_ms: float = 400  # a phone as the robot's microphone: not heard this long after the speaker ends
    voice_audio: str = "auto"  # auto | head | local ([voice] audio): Kaiku's Live voice and the microphone
    tap_back: TapBackConfig = field(default_factory=TapBackConfig)  # [tap_back]: the drum step as a rhythm game
    photo_time_s: float = 8  # [photo_time] seconds: how long the robot's camera counts face signs
    transcript_to_phone: bool = True  # [hub] transcript_to_phone: her words to the phone that is the microphone (D63)
    camera_window_s: float = 30  # [photo_time] conversation_window_s: one window of counting while she said yes (D61)
    expr_enabled: bool = True     # [robot_expression]: a visible change in her smile -> one gentle question (D60)
    expr_lower_max: float = 0.03  # a window with at most this share of smiling ...
    expr_earlier_min: float = 0.12  # ... after one in this conversation with at least this = lower
    expr_brighter_min: float = 0.35
    expr_min_coverage: float = 0.5
    expr_every_s: float = 90.0
    expr_max_n: int = 3
    track_enabled: bool = True   # [follow_track]: small head turns that keep her face in the camera's picture (D62)
    track_sign: int = 1          # 1 or -1: which way this robot's motor turns for a positive pan
    track_edge: float = 0.45     # |x_norm| past which the head turns toward her
    track_speed: float = 1.0     # motor speed of one nudge, 0-1 (below full speed the head did not visibly move)
    turn_s: float = 2.0          # [follow_track] turn_s: how long one asked-for turn of the head lasts
    track_nudge_deg: float = 10.0  # the length of one nudge: not an angle, 15 ms a "degree" (10 = 150 ms)
    track_every_s: float = 2.0   # at most one turn this often
    track_max_misses: int = 3    # turns in a row with her no nearer the middle before giving up for a while
    track_give_up_s: float = 60.0
    # models (VERIFY in docs; never hard-code in code)
    gemini_live_model: str = ""
    lyria_model: str = ""
    # attention ladder ([attention]; AttentionConfig picks the keys it knows)
    attention: dict = field(default_factory=dict)
    face_source: str = "laptop"  # laptop | unoq_yolo | off
    voice_name: str = ""
    mind_timeout_s: float = 120.0
    hub_transcripts: bool = False
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
        h = c.get("hub", {})
        return cls(
            home_id=env.get("KAIKU_HOME_ID") or c.get("home", {}).get("id", "demo-aino"),
            language=c.get("home", {}).get("language", "en"),
            greeting_language=c.get("home", {}).get("greeting_language", "en"),
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
            store_path=(resolve_path(str(h.get("store_path") or "logs/hub_sessions.sqlite"))
                        if h.get("store_enabled", True) else None),
            store_retention_days=_f(c, "hub", "store_retention_days", 30),
            store_max_mb=_f(c, "hub", "store_max_mb", 200),
            engagement_enabled=bool(h.get("engagement_enabled", True)),
            head_mode=(str(h.get("head_mode", "auto")).lower()
                       if str(h.get("head_mode", "auto")).lower() in ("auto", "follow", "drive") else "auto"),
            robot_home_id=str(h.get("robot_home_id") or "").strip() or None,
            head_stale_s=_f(c, "hub", "head_stale_s", 15),
            talk_idle_end_s=_f(c, "hub", "talk_idle_end_s", 180),
            follow_offer_every_s=_f(c, "hub", "follow_offer_every_s", 300),
            trace=bool(h.get("trace", True)),
            presence_leave_s=_f(c, "hub", "presence_leave_s", 6),
            presence_stale_s=_f(c, "hub", "presence_stale_s", 5),
            quality_min=_f(c, "perception", "quality_min", 0.5),
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
            dial_input=str(c.get("robot", {}).get("dial_input", "ear")),
            press_window_s=_f(c, "robot", "press_window_s", 4.0),
            drum_sway=bool(c.get("robot", {}).get("drum_sway", True)),
            phq9_every_days=_f(c, "ritual", "phq9_every_days", 14),
            presence_near_cm=_f(c, "perception", "presence_near_cm", 80),
            first_of_day_after_h=_f(c, "perception", "presence_first_of_day_after_h", 4),
            tap_refractory_ms=_f(c, "perception", "tap_refractory_ms", 80),
            tap_force_max_g=_f(c, "perception", "tap_force_max_g", 4.0),
            ppg_band_hz=(float(band[0]), float(band[1])),
            ppg_min_clean_ratio=_f(c, "perception", "ppg_min_clean_ratio", 0.7),
            light_enabled=bool(c.get("perception", {}).get("light_enabled", False)),
            light_window_min=_f(c, "perception", "light_window_min", 60),
            bpm_min=_f(c, "music", "bpm_min", 60),
            bpm_max=_f(c, "music", "bpm_max", 200),
            music_out=(str(c.get("music", {}).get("out", "head")).lower()
                       if str(c.get("music", {}).get("out", "head")).lower() in ("head", "speaker", "file") else "head"),
            head_lead_ms=_f(c, "music", "head_lead_ms", 80),
            head_gain=_f(c, "music", "head_gain", 0.8),
            phone_mic_tail_ms=_f(c, "voice", "phone_mic_tail_ms", 400),
            voice_audio=(str(c.get("voice", {}).get("audio", "auto")).lower()
                         if str(c.get("voice", {}).get("audio", "auto")).lower() in ("auto", "head", "local") else "auto"),
            photo_time_s=min(30.0, max(2.0, _f(c, "photo_time", "seconds", 8))),
            camera_window_s=min(30.0, max(5.0, _f(c, "photo_time", "conversation_window_s", 30))),
            transcript_to_phone=bool(c.get("hub", {}).get("transcript_to_phone", True)),
            expr_enabled=bool(c.get("robot_expression", {}).get("enabled", True)),
            expr_lower_max=_f(c, "robot_expression", "lower_smile_max", 0.03),
            expr_earlier_min=_f(c, "robot_expression", "earlier_smile_min", 0.12),
            expr_brighter_min=_f(c, "robot_expression", "brighter_smile_min", 0.35),
            expr_min_coverage=_f(c, "robot_expression", "min_coverage", 0.5),
            expr_every_s=_f(c, "robot_expression", "every_s", 90.0),
            expr_max_n=int(_f(c, "robot_expression", "max_per_conversation", 3)),
            track_enabled=bool(c.get("follow_track", {}).get("enabled", True)),
            track_sign=-1 if _f(c, "follow_track", "sign", 1) < 0 else 1,
            track_edge=_f(c, "follow_track", "edge", 0.45),
            track_speed=min(1.0, max(0.1, _f(c, "follow_track", "speed", 1.0))),
            turn_s=min(6.0, max(0.6, _f(c, "follow_track", "turn_s", 2.0))),
            track_nudge_deg=min(40.0, max(8.0, _f(c, "follow_track", "nudge_deg", 10.0))),
            track_every_s=max(0.8, _f(c, "follow_track", "every_s", 2.0)),
            track_max_misses=int(_f(c, "follow_track", "max_misses", 3)),
            track_give_up_s=_f(c, "follow_track", "give_up_s", 60.0),
            tap_back=TapBackConfig.from_dict(c.get("tap_back", {}), bpm_min=_f(c, "music", "bpm_min", 60),
                                             bpm_max=_f(c, "music", "bpm_max", 200)),
            gemini_live_model=str(c.get("models", {}).get("gemini_live", "")),
            lyria_model=str(c.get("models", {}).get("lyria_realtime", "")),
            attention=dict(c.get("attention", {})),
            face_source=str(c.get("attention", {}).get("face_source", "laptop")),
            voice_name=str(c.get("voice", {}).get("name", "")),
            mind_timeout_s=_f(c, "live", "mind_timeout_s", 120.0),
            hub_transcripts=bool(c.get("live", {}).get("hub_transcripts", False)),
            local_tts=env.get("KAIKU_LOCAL_TTS", "0") == "1",
            voice_timeout_s=_f(c, "attention", "voice_timeout_s", 3.0),
            helpline_name=c.get("safety", {}).get("helpline_name", "MIELI Crisis Helpline"),
            helpline_number=c.get("safety", {}).get("helpline_number", "09 2525 0111"),
            emergency_number=c.get("safety", {}).get("emergency_number", "112"),
        )


def model_id_ok(model_id: str) -> bool:
    """Model IDs in config start as VERIFY-... placeholders until someone checks the docs."""
    return bool(model_id) and not model_id.upper().startswith("VERIFY")
