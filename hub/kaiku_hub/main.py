"""Kaiku hub: wires adapters <-> bus <-> perception/rituals/safety <-> uplink.

    uv run python -m kaiku_hub.main            # or: make hub
    KAIKU_VOICE=text  -> type in the terminal (start / skip / 1-5 dial / 0-3 PHQ-9 / yes / no)
    KAIKU_VOICE=off   -> fully sensor-driven (sims or hardware)

Everything the hub produces is an obs.* envelope: published on the bus AND queued for the cloud.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import shutil
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from kaiku_contracts import ContractError, Envelope, ParsedTopic, make
from kaiku_contracts.api import EpisodeIn, EpisodeOutcome
from kaiku_contracts.companion_tools import TOOLS as REGISTRY
from kaiku_contracts.companion_tools import validate_args
from kaiku_contracts.config import load_dotenv
from kaiku_contracts.jlog import get_logger

from . import __version__, follow
from .attention import Attention, AttentionConfig
from .bus import Bus
from .cloudlink import CloudLink, local_nudge
from .devices.atech_adapter import AtechAdapter
from .devices.lora_serial import LoraSerialAdapter
from .devices.unoq_yolo import UnoqYoloFaces
from .episodes import EpisodeOutbox
from .follow import HeadFollower
from .live import Music, Voice, make_music, make_voice
from .live.context_events import ContextEvents, DrumFeel, breathing_calmer, late_key, light_key
from .live.head_audio import HeadAudio, HeadSpeaker
from .live.lines import LinePlayer
from .live.tools import (
    ASK_TWICE_KINDS,
    ASK_TWICE_S,
    CAMERA_LINE,
    CAMERA_OFF_LINE,
    CAMERA_ON_LINE,
    CAMERA_RING,
    CAMERA_WAIT_S,
    EXPRESSION_CUE,
    HEAD_RUNS_ITS_STEPS,
    LIGHT_COLOURS,
    REST_RING,
    TOOLS,
    with_ask_twice,
    without,
)
from .perception import face
from .perception.engagement import EngagementTracker
from .perception.light import LightAggregator
from .perception.presence import PresenceTracker
from .perception.presses import PressCounter
from .perception.tap_back import OneTapSource
from .rituals import Event, RitualMachine, default_steps, steps, tap_back
from .rituals.photo_time import PhotoTime
from .safety import ButtonLongPress, CrisisScript, SafetyGate, Trigger
from .settings import Settings
from .state import HubState
from .store import SessionStore
from .uplink import Uplink

log = get_logger("hub")
CLOUD_TOOLS = frozenset(n for n, t in REGISTRY.items() if t.get("executor") == "cloud")
# Cloud tools the model calls WITHOUT pausing (feel): Kaiku keeps listening, so no thinking pose and no spoken
# "let me think" line; the answer goes back with the `scheduling` the result carries.
BACKGROUND_TOOLS = frozenset(n for n in CLOUD_TOOLS if REGISTRY[n].get("behavior") == "NON_BLOCKING")

SIM_WINDOW_S = 60.0
CRISIS_DEDUPE_S = 60.0
HELP_S = 600.0  # the head takes its help screen down by itself after this long (firmware HELP_SHOW_MS)
HELP_RESEND_AFTER_S = 2.0  # a health message already on its way when the help screen was sent says nothing yet
ATTENTION_HZ = 5.0
THINK_TIMEOUT_S = 8.0  # a cloud tool (ask_mind, recall, ...) slower than this -> scripted line, ritual goes on
THINK_LATER = "Let me think about that later."
QUIET = re.compile(r"\b(not now|quiet|be quiet|hiljaa|ei nyt|tyst|inte nu)\b", re.I)


def _answered_by(who: Any) -> str | None:
    """Who answered a tool, in the trace's few words, from what the cloud's result says (a rule, or a model's name).
    Anything else = not known."""
    if not isinstance(who, str):
        return None
    w = who.lower()
    return next((k for k in ("rule", "notebook", "gemma", "flash", "argon") if k in w), None)


class Hub:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        voice: Voice | None = None,
        music: Music | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        read_stdin: bool = True,
    ):
        self.settings = s = settings or Settings.load()
        self.state = HubState(s.state_path)
        # The bus home is the robot's (what the boards were flashed with); observations are stamped with the
        # person's record id (settings.home_id). They are usually the same; `[hub] robot_home_id` splits them.
        self.bus_home = s.robot_home_id or s.home_id
        self.bus = Bus("hub", home_id=self.bus_home, version=__version__, details=self._details)
        # The robot's own body for sound (plan 07 section 4): the head's speaker and microphone over the bus. The
        # one HeadSpeaker is shared by the music, its cues and Kaiku's voice, so their frames can never interleave.
        self.speaker = HeadSpeaker(self.bus.publish_audio, lead_ms=s.head_lead_ms, gain=s.head_gain)
        self.head_audio = HeadAudio(self.speaker, self._head_audio_cmd, phone_tail_ms=s.phone_mic_tail_ms)
        self.voice = voice or make_voice(s.voice, model_id=s.gemini_live_model, language=s.language,
                                         read_stdin=read_stdin, voice_name=s.voice_name, audio=s.voice_audio,
                                         head=self.head_audio, head_alive=self._head_alive)
        self.music = music or make_music(s.music, model_id=s.lyria_model, bpm_min=s.bpm_min, bpm_max=s.bpm_max,
                                         out=s.music_out, head=self.speaker)
        self.uplink = Uplink(url=s.cloud_url, token=s.home_token, queue_path=s.queue_path,
                             batch_s=s.uplink_batch_s, max_batch=s.uplink_max_batch, timeout_s=s.uplink_timeout_s,
                             transport=transport)
        self.cloud = CloudLink(url=s.cloud_url, home_id=s.home_id, token=s.home_token, transport=transport)
        self.episodes = EpisodeOutbox(s.queue_path.with_name("robot_episodes.sqlite"), self.cloud)
        self._episode: dict | None = None
        self.gate = SafetyGate.from_file()
        self.script = CrisisScript.from_file()
        self.button = ButtonLongPress(hold_s=2.0)
        self.presses = PressCounter(window_s=s.press_window_s)
        self._press_task: asyncio.Task | None = None
        self.presence = PresenceTracker(s.presence_near_cm, s.first_of_day_after_h, last_arrival=self.state.last_arrival,
                                        leave_s=s.presence_leave_s, stale_s=s.presence_stale_s)
        self.store = SessionStore(s.store_path, retention_days=s.store_retention_days, max_mb=s.store_max_mb)
        self.engagement = EngagementTracker()
        self._in_session = False  # a ritual is open: raw + obs are stored and feed the engagement summary
        # Follow mode (follow.py): a standalone head runs the ritual itself; the hub records it and sends no cmd.head.
        self.follower = HeadFollower(
            refractory_ms=s.tap_refractory_ms, force_max_g=s.tap_force_max_g, stale_s=s.head_stale_s,
            ppg_band_hz=s.ppg_band_hz, ppg_min_clean_ratio=s.ppg_min_clean_ratio, hrv_window_s=s.hrv_window_s,
            quality_min=s.quality_min,
            unanswered_gap_s=float(s.attention.get("regreet_h", 3)) * 3600)
        self.head_firmware: str | None = None  # from health/head details.firmware ("standalone" | "mqtt")
        self.head_cmds_held = 0  # cmd.head not sent because the head runs its own ritual
        self._other_homes: set[str] = set()
        self._ritual_consented = False  # the person accepted the conversation at some point in this ritual
        self._notes: dict[str, dict] = {}  # "not measured" reasons etc. for the stored session summary
        self._last_face: tuple[float, dict] | None = None
        self.light = LightAggregator(s.light_window_min)
        self.machine = RitualMachine(self, default_steps(s), step_timeout_s=s.step_timeout_s)
        self._drum_step = next((st for st in self.machine.steps if st.name == "drum"), None)
        self.tap_source = OneTapSource()  # the knock switch and the head's motion sensor can both feel one tap
        self._game: tap_back.Game | None = None  # Tap it back run by the hub inside a standalone head's drum step
        self.photo_time = PhotoTime(s.photo_time_s)  # the camera's face-signs moment (rituals/photo_time.py)
        self._game_task: asyncio.Task | None = None
        self.lora = LoraSerialAdapter(self.emit)
        self.atech = AtechAdapter() if s.head == "atech" else None
        self.attention = Attention(AttentionConfig.from_dict(s.attention))
        self.lines = LinePlayer(cloud_url=s.cloud_url, token=s.home_token, timeout_s=s.voice_timeout_s,
                                play_audio=s.voice in ("gemini", "local") or s.local_tts, transport=transport,
                                head=self.speaker, on_head=self._lines_on_head)
        if self.voice.wants_session:
            self.voice.fallback_say = lambda text: self.lines.say_text(text, s.language)
            self.voice.keep_transcript = s.hub_transcripts
            self.voice.on_partial_utterance = self.on_partial_utterance
            self.voice.on_completed_utterance = self.on_live_utterance
            self.voice.on_speech_features = self.on_speech_features
        self.face = face.FaceTracker(self._on_face) if s.face_source == "laptop" and face.available() else None
        self.unoq_faces = UnoqYoloFaces(self.sensors) if s.face_source == "unoq_yolo" else None
        self.conversation_consented = False
        self._talk_used = False  # this ritual's one conversation was opened (reset when the next ritual begins)
        self._asked: dict[str, Any] | None = None  # asking twice (D58): {kind, until, n} while a press is awaited
        self._asked_n = 0
        # The camera, asked once per conversation on the robot (D61): None = not answered (off), True / False = her
        # answer. Reset when a ritual begins; nothing but `camera_choice` sets it.
        self._camera: bool | None = None
        self._camera_asked = False
        self._camera_answered = asyncio.Event()
        self._camera_task: asyncio.Task | None = None
        self._expr_best, self._expr_n, self._expr_at = 0.0, 0, 0.0   # `_expression_cue`: this conversation's
        self._expr_last: str | None = None                            # highest smile share, cues sent, the last kind
        # Keeping her in view on a head that runs its own ritual (D62): small turns toward her face when it drifts
        # to the edge of the camera's picture. See `_follow_track`.
        self._track_at = 0.0           # when the last turn was asked for
        self._track_from: float | None = None   # where her face was then (x_norm)
        self._track_misses = 0         # turns in a row that did not bring her nearer the middle
        self._track_pause_until = 0.0
        self._live_open_task: asyncio.Task | None = None
        self.ritual_reason = ""
        self.node_health: dict[str, dict] = {}
        self._sim_until = 0.0
        self._last_ritual_end = -1e9
        self._last_crisis: dict[str, float] = {}
        self._seen_cmds: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self.emitted: list[Envelope[Any]] = []  # in-process tap for tests/debugging (bounded)
        self.context = ContextEvents(self._send_context)  # T5 live events, one "session" per ritual
        self.drum_feel = DrumFeel(refractory_ms=s.tap_refractory_ms)
        self.think_timeout_s = THINK_TIMEOUT_S
        self.thinking = 0  # cloud tool calls in flight (body shows "thinking")
        self._eyes = "neutral"  # last eyes the ritual/attention asked for (restored after thinking)
        self._crisis_n = 0
        # raw.hub.trace: what Kaiku says and does, live, for the apps' "Kaiku bot" tab (home network only)
        self._trace_tasks: set[asyncio.Task] = set()
        self._trace_quiet = False  # after a crisis nothing is traced but the script line, until the next ritual
        self._music_on = False
        self._trace_music()
        if hasattr(self.voice, "on_reply"):
            self.voice.on_reply = lambda text: self.trace("said", text=text, by="live")
            self.voice.on_session = lambda opened: self.trace("session", detail="open" if opened else "close")
        self._help_shown = False  # the crisis path asked the head for its help screen; cleared when a ritual starts
        self._help_at = -1e9       # ... when; the head takes it down by itself HELP_S later
        self._help_seen = False    # ... and the head's health has said `help_shown: true` since
        self._help_resent = False  # ... or it was sent once more, to a head that was off the broker the first time
        self._follow_step_seen: str | None = None  # the head's own step Kaiku last spoke for (follow mode)
        self._follow_offer_at = -1e9
        self._talk_n = 0  # conversations opened while following (a late goodbye never closes a newer one)

    # ================================================================ RitualContext
    async def say(self, text: str) -> None:
        # In an open Live conversation the voice says the line in its own words: its reply is traced as spoken.
        if not getattr(self.voice, "in_session", False):
            self.trace("said", text=text, by="cached_voice" if self.voice_audible else "script")
        try:
            if self.settings.voice == "local":
                await self.lines.say_text(text, self.settings.language)
            else:
                await self.voice.say(text)
        except Exception as e:
            log.warning("voice_failed", str(e))

    async def head(self, **cmd: Any) -> None:
        if cmd.get("eyes"):
            self._eyes = cmd["eyes"]
        # `drum: hold|end` is the one family of commands a head that runs its own ritual takes from the hub (D51)
        if "drum" in cmd:
            await self._cmd("cmd.head", cmd, force=True)
        else:
            await self._cmd("cmd.head", cmd)

    @property
    def voice_audible(self) -> bool:
        """Kaiku's lines are really spoken (Live, or the cached Gemini voice): the game leaves room for them."""
        return self.settings.voice in ("gemini", "local") or self.settings.local_tts

    def trace(self, kind: str, *, crisis_script: bool = False, **fields: Any) -> None:
        """One `raw.hub.trace` on the home broker (QoS 0, never uplinked, never stored): Kaiku's own lines, the name
        of a tool the voice called, a game cue, music, a session opening or closing. NEVER the person's words, a
        tool's arguments or its result. Returns at once and never raises: the ritual does not wait for it."""
        if not self.settings.trace or (self._trace_quiet and not crisis_script):
            return
        payload = {"kind": kind, **{k: v for k, v in fields.items() if v is not None}}
        if isinstance(payload.get("text"), str):
            payload["text"] = payload["text"][:300]
        try:
            task = asyncio.get_running_loop().create_task(self._trace_send(payload), name="trace")
        except RuntimeError:
            return  # no loop (a unit test of a step): nothing to tell
        self._trace_tasks.add(task)
        task.add_done_callback(self._trace_tasks.discard)

    async def _trace_send(self, payload: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(self.bus.publish("raw.hub.trace", payload), timeout=2.0)
        except Exception as e:  # never the payload in a log
            log.debug("trace_not_sent", type(e).__name__)

    def _trace_music(self) -> None:
        """Music start / song / hush / stop go on the trace too. The adapter's own methods are wrapped on this one
        instance, whichever adapter it is; `hush` and `stop` are only told when something was playing."""
        def wrap(name: str) -> None:
            inner = getattr(self.music, name, None)
            if inner is None:
                return

            async def traced(*args: Any, **kwargs: Any) -> Any:
                out = await inner(*args, **kwargs)
                with contextlib.suppress(Exception):
                    if name == "song":
                        if out:  # "" = no song could play
                            self._music_on = True
                            self.trace("music", detail="song", bpm=float(args[0]) if args else None)
                    elif name == "start":
                        self._music_on = True
                        self.trace("music", detail="start")
                    elif self._music_on:
                        self._music_on = name == "hush"  # a hush keeps the adapter running; stop ends it
                        self.trace("music", detail=name)
                return out

            with contextlib.suppress(Exception):
                setattr(self.music, name, traced)

        for name in ("start", "song", "hush", "stop"):
            wrap(name)

    async def listening(self, on: bool) -> None:
        """Close (False) or reopen (True) the microphone of the open conversation, without ending it. Tap it back
        closes it for the whole game: the song and her taps are not speech. No conversation = nothing to do."""
        if on and not self.conversation_consented:
            return  # the conversation is over (a crisis, or she asked to stop): nothing opens the microphone again
        listen = getattr(self.voice, "listen", None)
        if listen is not None:
            listen(on)

    def _ritual_open(self) -> bool:
        """A ritual is running: the hub's own, or the head's own that the hub follows."""
        return self.machine.running or (self.following and self.follower.active)

    def _clear_help(self) -> None:
        """A new ritual starts: the head's help screen (crisis path) is taken down. The head also clears it by
        itself on its own new ritual and after 10 minutes."""
        self._trace_quiet = False
        if self._help_shown:
            self._help_shown = self._help_seen = False
            self._tasks.append(asyncio.create_task(self._cmd("cmd.head", {"show": "none"}, force=True),
                                                   name="help-clear"))

    async def _show_help(self, **also: Any) -> bool:
        """The crisis path's one command to the head's screen: `cmd.head {show: help}` (plus `also`, in the same
        message). Never raises; the script and the safety flag follow whatever happens here."""
        try:
            await self._cmd("cmd.head", {**also, "show": "help"}, force=True)
        except Exception as e:
            log.warning("help_screen_not_sent", type(e).__name__)
            return False
        self._help_shown, self._help_at = True, time.monotonic()
        self._help_seen = self._help_resent = False
        return True

    async def _help_health(self, details: dict) -> None:
        """`cmd.head` is not retained: a head that was off the broker at the crisis missed the help screen. Its
        health says so (`details.help_shown`). Sent ONCE more, and only to a head that never showed it: one that
        showed it and took it down (she pressed its ear, `show: none`, its own ten minutes) is left alone."""
        shown = details.get("help_shown")
        if not self._help_shown or shown is None or time.monotonic() - self._help_at >= HELP_S:
            return
        if details.get("help_screen") == "none":
            return  # a head with no screen (this robot): it has nothing to show, and it took the command as "stop"
        if shown:
            self._help_seen = True
        elif not self._help_seen and not self._help_resent and time.monotonic() - self._help_at >= HELP_RESEND_AFTER_S:
            self._help_resent = True
            log.info("help_screen_resent", "the head's health says it is not showing the help screen")
            with contextlib.suppress(Exception):
                await self._cmd("cmd.head", {"show": "help"}, force=True)

    @property
    def speaker_busy(self) -> bool | None:
        """The head's speaker still has sound of ours to play (music, a chime, Kaiku's voice). The head sends no tap
        then, so Tap it back opens her turn only after it. None = nothing was ever sent to the head's speaker (the
        sound goes to a sound card or nowhere): not known."""
        return self.speaker.playing if self.speaker.frames else None

    def _lines_on_head(self) -> bool:
        """Scripted lines in Kaiku's cached voice go where the Live voice goes (`[voice] audio`): the head's own
        speaker, or this machine's player. auto = the head when one is alive, or when this machine has no player."""
        choice = self.settings.voice_audio
        if choice == "auto":
            return self._head_alive() or not (shutil.which("afplay") or shutil.which("aplay"))
        return choice == "head"

    def _head_alive(self) -> bool:
        """A real head that can sound is on the bus and not down (its last heartbeat says so): its `health/head`
        carries the `audio` block of the sound firmware. A head still on the firmware without sound is not a body
        to speak through, and neither is a simulated one: with `auto`, the voice then stays on this machine."""
        health = self.node_health.get("head") or {}
        details = health.get("details") or {}
        return (health.get("status") not in (None, "down") and not details.get("sim")
                and isinstance(details.get("audio"), dict))

    def _head_can_hold(self) -> bool:
        """The head's firmware can lend the hub its drum step (`cmd.head {drum: hold}`): its `health/head` then
        reports `drum_held`. A head that cannot would leave its drum step on its own timer in the middle of a game
        and sound its own tap tones over it, so no game is started on it."""
        return "drum_held" in ((self.node_health.get("head") or {}).get("details") or {})

    async def _head_audio_cmd(self, **cmd: Any) -> None:
        """`cmd.head {mic: open|close}`: also for a head that runs its own ritual (it only opens its microphone)."""
        await self._cmd("cmd.head", cmd, force=True)

    async def _send_context(self, text: str) -> None:
        if self.conversation_consented:
            await self.voice.send_context(f"[source: robot] {text}")

    async def notice(self, key: str | None) -> bool:
        """Context event for the open Live session (live/context_events.py rules); dropped if no ritual."""
        return bool(key) and await self.context.notice(key)

    async def sensors(self, **cmd: Any) -> None:
        await self._cmd("cmd.sensors", cmd)

    def note(self, event: str, **fields: Any) -> None:
        """Something worth keeping with the session that is NOT an observation (e.g. why the pulse was not
        measured). Logged, stored in the local session summary, never uplinked."""
        log.info(event, str(fields.get("reason", "")), **{k: v for k, v in fields.items() if k != "reason"})
        self._notes[event] = fields
        if event == "pulse_not_measured":
            self.engagement.hrv_reason = str(fields.get("reason", ""))

    @property
    def following(self) -> bool:
        """True when the head runs the ritual itself and the hub only records it ([hub] head_mode)."""
        mode = self.settings.head_mode
        return mode == "follow" or (mode == "auto" and self.head_firmware == "standalone")

    async def _cmd(self, type_: str, payload: dict, *, force: bool = False) -> None:
        if type_ == "cmd.head" and self.following and not force:
            # The standalone head turns every `pan` into a 600 ms open-loop motor run and owns its eyes per step:
            # hub ritual / attention commands would fight it.
            self.head_cmds_held += 1
            return
        try:
            await self.bus.publish(type_, payload)
        except ContractError as e:
            log.error("bad_command", str(e)[:300], type=type_)

    @property
    def is_sim(self) -> bool:
        return time.monotonic() < self._sim_until

    async def emit(self, type_: str, payload: dict, quality: float | None = None, *,
                   ts: datetime | None = None) -> Envelope[Any] | None:
        """Every observation goes through here: validate -> bus -> uplink queue."""
        try:
            env = make(type_, payload, source="hub", home_id=self.settings.home_id, quality=quality, sim=self.is_sim, ts=ts)
        except ContractError as e:
            log.error("emit_invalid", str(e)[:300], type=type_)
            return None
        self.uplink.enqueue(env)  # durable queue first: a stop during the publish must not lose it for the cloud
        await self.bus.publish_env(env if env.home_id == self.bus_home
                                   else env.model_copy(update={"home_id": self.bus_home}))
        if self._in_session:
            self.store.add_obs(env)
            self.engagement.on_obs(type_, payload, quality)
        self.emitted.append(env)
        del self.emitted[:-500]
        log.info("obs", type_, **{k: v for k, v in payload.items()
                                  if isinstance(v, (int, float, str, bool)) and k not in ("level", "event", "msg")})
        if type_ == "obs.intervention_response" and breathing_calmer(payload):
            await self.notice("breathe.calmer")
        if type_ == "obs.phq9":  # safety gate on PHQ-9 answers, whichever step produced them
            trig = SafetyGate.check_phq9(item9_positive=env.payload.item9_positive)
            if trig:
                self._tasks.append(asyncio.create_task(self.crisis(trig), name="crisis"))
        return env

    async def on_speech_features(self, features: dict) -> None:
        # Numeric summaries only, and only inside the explicitly accepted conversation.
        if self.conversation_consented and self.machine.running:
            await self.emit("obs.speech_features", features)

    async def get_nudge(self) -> tuple[str, str]:
        suggested = self.state.take_suggested_arm()
        if suggested:
            return local_nudge(suggested)
        res = await self.cloud.get_nudge()
        if res is not None:
            return res.arm, res.reason
        return local_nudge()

    # ================================================================ ritual control
    def start_ritual(self, reason: str) -> bool:
        if self.following:
            log.info("ritual_start_refused", "the head runs its own ritual (follow mode); press its ear to start",
                     reason=reason)
            return False
        if self.machine.running:
            return False
        log.info("ritual_start", reason)
        self._clear_help()
        self._episode = {"id": str(uuid4()), "start": datetime.now(UTC), "outcome": "completed", "tools_used": []}
        self.ritual_reason = reason
        self.conversation_consented = reason in ("text", "button", "cli", "test")
        self._ritual_consented = self.conversation_consented
        self.engagement.reset()
        self._notes = {}
        self.store.begin(self._episode["id"], reason, home_id=self.settings.home_id, sim=self.is_sim)
        self._in_session = True
        task = self.machine.start()
        if task:
            task.add_done_callback(self._ritual_done)
            self.context.open_session()
            self.drum_feel.reset()
            self._tasks.append(asyncio.create_task(self.notice(late_key(datetime.now().astimezone().hour)),
                                                   name="context-late"))
            if self.conversation_consented:
                self.accept_conversation()
        return task is not None

    def accept_conversation(self) -> None:
        self.conversation_consented = True
        self._ritual_consented = True
        if self.voice.wants_session and (self._live_open_task is None or self._live_open_task.done()):
            self._live_open_task = asyncio.create_task(self._open_live(), name="live-open")
            self._tasks.append(self._live_open_task)

    async def end_ritual(self, *, outcome: EpisodeOutcome = "ended_early", open_thread: dict | None = None) -> None:
        if self._episode:
            self._episode["outcome"] = outcome
            self._episode["_explicit_outcome"] = True
            if open_thread:
                self._episode["open_thread"] = open_thread
        self.conversation_consented = False
        if self._live_open_task and not self._live_open_task.done():
            self._live_open_task.cancel()
        if self.following and self.follower.active:
            # She asked to stop (D59): the head goes back to rest now. What was answered so far is already sent;
            # the follower closes the open step and the episode when the head reports idle (`_follow_end`).
            self._asked = None
            with contextlib.suppress(Exception):
                await self._cmd("cmd.head", {"ritual": "end"}, force=True)
        await self.machine.abort()
        await self.voice.close_session()

    async def _open_live(self) -> None:
        """Open only after explicit consent and an authorized, healthy cloud bootstrap."""
        sess = await self.cloud.companion_session("ritual")
        self._session_id = (sess or {}).get("session_id")
        if self._episode and self._session_id:
            self._episode["id"] = self._session_id
        if sess:
            instruction, tools = sess["system_instruction"], sess.get("tools") or TOOLS
            model, voice, origin = sess.get("model") or None, sess.get("voice") or None, "cloud"
        else:
            log.warning("live_session_unavailable", "cloud bootstrap required")
            return
        if not self._ritual_open() or not self.conversation_consented:
            return
        if self.following:
            # the head moves through its own steps and takes the dial from its own knob: the model is not offered
            # tools the hub cannot honour there (`on_tool` refuses them too)
            tools = with_ask_twice(without(tools, HEAD_RUNS_ITS_STEPS))  # start_activity only as asking twice (D58)
        if sess.get("max_session_seconds"):
            self.voice.max_seconds = float(sess["max_session_seconds"])
        ok = await self.voice.open_session(instruction, tools, model=model, voice=voice)
        log.info("live_session", origin, opened=ok, persona=(sess or {}).get("persona_version", "local"))
        if ok and self.following:
            await self._ask_camera_once()

    def _close_session(self, episode_id: str | None, outcome: str, consented: bool) -> None:
        """End of a ritual, synchronously (a new ritual may start right away): build the multi-cue summary (only
        for an accepted conversation, never after a crisis), close the local session record, then emit the
        summary as obs.engagement and link it to the stored session."""
        sid, summary = self.store.session_id, None
        try:
            self.engagement.camera_seen = self.attention.faces_seen
            if (self.settings.engagement_enabled and consented and outcome != "crisis"
                    and self.engagement.steps_started > 1):
                summary = self.engagement.summary(episode_id)
        except Exception as e:  # the summary must never break the end of a ritual
            log.error("engagement_failed", f"{type(e).__name__}: {e}")
        self._in_session = False
        self.store.end(outcome=outcome, episode_id=episode_id, sim=self.is_sim,
                       summary={"engagement": summary, "notes": self._notes, "consented": consented})
        if summary is None:
            return

        async def send() -> None:
            env = await self.emit("obs.engagement", summary, quality=summary["confidence"])
            if env is not None and sid is not None:
                self.store.add_obs(env, session_id=sid)
                self.store.flush()

        with contextlib.suppress(RuntimeError):  # no running loop at interpreter shutdown
            self._tasks.append(asyncio.get_running_loop().create_task(send(), name="engagement"))

    def _ritual_done(self, task: asyncio.Task) -> None:
        consented = self._ritual_consented
        self._ritual_consented = False
        closing = (self._episode or {}).get("id"), "aborted"
        if self._episode:
            episode, self._episode = self._episode, None
            explicit_outcome = episode.pop("_explicit_outcome", False)
            if task.cancelled() and episode["outcome"] == "completed" and not explicit_outcome:
                episode["outcome"] = "ended_early"
            if not self.conversation_consented and episode["outcome"] == "completed" and not explicit_outcome:
                episode["outcome"] = "skipped"
            if episode["outcome"] == "crisis":
                episode.pop("open_thread", None)
            closing = episode["id"], episode["outcome"]
            transcript = getattr(self.voice, "transcript", None)
            self.episodes.enqueue(EpisodeIn(
                home_id=self.settings.home_id, surface="robot", intent="ritual", end=datetime.now(UTC),
                transcript=transcript if self.settings.hub_transcripts and episode["outcome"] != "crisis" else None,
                **episode))
            if hasattr(self.voice, "transcript"):
                self.voice.transcript = []
        self.conversation_consented = False
        if self._live_open_task and not self._live_open_task.done():
            self._live_open_task.cancel()
        self._close_session(closing[0], closing[1], consented)
        self._last_ritual_end = time.monotonic()
        self.ritual_reason = ""
        self.context.close_session()
        if self.voice.wants_session and not task.cancelled():
            self._tasks.append(asyncio.create_task(self.voice.close_session()))
        if task.cancelled():
            return
        if task.exception() is not None:
            log.error("ritual_failed", repr(task.exception()))
            return
        results = task.result()
        log.info("ritual_done", "", **results)
        if results.get("close") == "completed":
            self.state.mark_ritual_done(datetime.now().astimezone().date())

    # ================================================================ safety
    async def crisis(self, trigger: Trigger) -> None:
        """Deterministic crisis path. No LLM. Order matters (handoff §10)."""
        now = time.monotonic()
        if self._episode:
            self._episode["outcome"] = "crisis"
            self._episode.pop("open_thread", None)
        if hasattr(self.voice, "transcript"):
            self.voice.transcript = []
        self._crisis_n += 1
        self._asked = None  # nothing she asked for starts after this
        self._camera_reset()  # and the camera's counting for this conversation is over
        self._trace_quiet = True  # nothing but the script line goes on the trace from here
        self.conversation_consented = False
        if self._live_open_task and not self._live_open_task.done():
            self._live_open_task.cancel()
        # The microphone is shut before anything else and nothing reopens it (`listening(True)` needs a conversation
        # that is still wanted): a `mic: open` after the head's help screen would open it under that screen.
        with contextlib.suppress(Exception):
            await self.listening(False)
        self.context.close_session()  # nothing but the script after a crisis
        log.warning("safety_trigger", trigger.kind, matched=trigger.detail, lang=trigger.language)
        # 1. stop the ritual and any generated audio
        await self.machine.abort()
        helped = False
        if self.following:  # stop recording; the head itself has no "stop" over MQTT, so only its eyes are calmed
            if self._game is not None:  # nothing of a game is recorded after a crisis; the head gets its step back
                self._game = None
                if self._game_task is not None:
                    self._game_task.cancel()
                # ONE message with the help screen: the standalone firmware then drops the drum end silently (no
                # end chime, no "done" screen before the helpline's numbers). A firmware that does not know `show`
                # still gets its step back.
                helped = await self._show_help(drum="end", pan_mode="still")
            await self._follow_do(self.follower.abort(now, "crisis", "safety trigger"))
            await self._cmd("cmd.head", {"eyes": "soft"}, force=True)
        with contextlib.suppress(Exception):
            await self.music.stop()
        with contextlib.suppress(Exception):
            await self.voice.interrupt()
        # 2. calm body language
        await self.head(eyes="soft", chest="off", pan_mode="still")
        # 2b. the helpline's name and numbers on the head's own screen (constants compiled into its firmware;
        # never a sound). Both firmwares, so forced through in follow mode too. Already sent when a game was ended.
        if not helped:
            await self._show_help()
        # 3. scripted message, verbatim (+ helpline numbers always visible in logs/terminal)
        text = self.script.text(self.settings.language)
        self.trace("said", text=text, by="script", crisis_script=True)
        try:
            await self.voice.say_verbatim(text)
        except Exception:
            pass
        print(f"\n*** {text}\n*** {self.settings.helpline_name}: {self.settings.helpline_number} · "
              f"Emergency: {self.settings.emergency_number}\n", file=sys.stderr, flush=True)
        # 4. flag on the priority uplink (deduped per trigger kind)
        if now - self._last_crisis.get(trigger.kind, -1e9) >= CRISIS_DEDUPE_S:
            self._last_crisis[trigger.kind] = now
            await self.emit("obs.safety_flag", {"trigger": trigger.kind, "severity": "high", "handled_locally": True})

    async def check_utterance_safety(self, text: str) -> bool:
        """Scan partial speech immediately without treating it as a completed answer."""
        trig = self.gate.check_text(text)
        if trig:
            await self.crisis(trig)
            return True
        return False

    async def on_partial_utterance(self, text: str) -> None:
        await self.check_utterance_safety(text)

    async def on_live_utterance(self, text: str) -> None:
        # Live's named record_dial tool owns dial writes. Transcription and tool messages have
        # independent ordering, so also parsing the transcript would record the same answer twice.
        await self.on_utterance(text, live=True)

    async def on_utterance(self, text: str, *, live: bool = False) -> None:
        """Completed user speech/text enters here. Safety gate runs FIRST."""
        if await self.check_utterance_safety(text):
            return
        if live:
            self.trace("heard")  # she spoke: only that. Her words never travel on the trace
            if self.settings.transcript_to_phone and self.head_audio.phone_listening and text.strip():
                # D63: the phone that is the robot's microphone shows what was heard. Only while it is sending.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.bus.publish("raw.hub.transcript", {"text": text.strip()[:500]}), 2.0)
        cmd = text.strip().lower()
        now = datetime.now().astimezone()
        if not self.machine.running or self.machine.state == "greet":
            if QUIET.search(cmd):
                self.attention.quiet(now)
                log.info("quiet_mode", f"{self.attention.cfg.quiet_h} h")
            elif not self.machine.running:
                self.attention.person_started(now)
        if cmd in ("start", "aloita"):
            self.start_ritual("text")
        elif cmd in ("stop", "end", "cancel", "lopeta"):
            await self.end_ritual()
        elif cmd in ("skip", "ohita"):
            self.machine.feed(Event("skip"))
        elif self.machine.running:
            self.machine.feed(Event("utterance", {"text": text, "live": live}))

    async def on_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Every tool the voice calls: run it, then one trace with its NAME, how long it took, whether it worked and
        (only when the cloud's result says so) who answered. Never its arguments or its result."""
        t0 = time.monotonic()
        out: dict[str, Any] = {"ok": False}
        try:
            out = await self._run_tool(name, args)
            return out
        finally:
            who = out.get("by") if isinstance(out, dict) else None
            self.trace("tool", tool=str(name)[:40], ms=int((time.monotonic() - t0) * 1000),
                       ok=bool(out.get("ok")) if isinstance(out, dict) else False, by=_answered_by(who))

    async def _run_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Model requests; the hub decides. Cloud tools forward; end_session uses durable episode completion."""
        if self._episode and name not in self._episode["tools_used"]:
            self._episode["tools_used"].append(name)
        if name == "end_session":
            problems = validate_args(REGISTRY[name]["parameters"], args)
            if problems:
                return {"ok": False, "error": "; ".join(problems)}
            follow_up = args.get("follow_up")
            if follow_up:
                if await self.check_utterance_safety(follow_up["topic"]):
                    return {"ok": False, "error": "stopped"}
                if not follow_up["topic"].strip():
                    return {"ok": False, "error": "follow-up topic is empty"}
            await self.end_ritual(outcome=args.get("outcome", "completed"), open_thread=follow_up)
            return {"ok": True, "follow_up_queued": bool(follow_up)}
        if name == "end_ritual":
            await self.end_ritual()
            return {"ok": True}
        if name == "camera_choice":
            return await self._camera_choice(args)
        if name == "set_light":
            colour = LIGHT_COLOURS.get(str(args.get("colour")))
            if colour is None:
                return {"ok": False, "error": f"colours: {', '.join(LIGHT_COLOURS)}"}
            await self._cmd("cmd.head", {"color": colour}, force=True)
            return {"ok": True, "colour": args["colour"]}
        if name == "turn_head":
            if args.get("direction") not in ("left", "right"):
                return {"ok": False, "error": "direction is left or right"}
            if self._game is not None:
                return {"ok": False, "error": "not during the rhythm game: the head moves with the song"}
            # as SHE sees it; `[follow_track] sign` is which way this robot's motor turns for a positive pan
            way = (1 if args["direction"] == "right" else -1) * self.settings.track_sign
            await self._cmd("cmd.head", {"pan": {"target_deg": 30.0 * way, "speed": 0.6}}, force=True)
            self._track_pause_until = time.monotonic() + 20.0  # she placed the head: following waits a while
            return {"ok": True, "note": "It turns as soon as you stop speaking."}
        if name == "photo_time":
            if self.following and self._camera is not True:
                return {"ok": False, "error": "the camera is off for this conversation. Photo time needs it; they "
                                              "can ask for the camera to be turned on"}
            today = datetime.now().astimezone().date()
            first = not self.state.photo_time_done_on(today)
            out = await self.photo_time.run(self)
            if out.get("ok"):
                self.state.mark_photo_time(today)
                out = {**out, "today": "the first of today" if first else "already done once today; this one is kept too"}
            return out
        if self.following and name == "start_activity":
            return await self._ask_twice(args)
        if self.following and name == "record_dial":
            return await self._follow_spoken_dial(args)
        if self.following and name in HEAD_RUNS_ITS_STEPS:
            return {"ok": False, "error": "this head runs its own steps: she answers by turning the ear and pressing "
                                          "it, and a press moves on"}
        if name == "express":
            problems = validate_args(REGISTRY[name]["parameters"], args)
            if problems:
                return {"ok": False, "error": "; ".join(problems)}
            if not self.conversation_consented or not self.machine.running:
                return {"ok": False, "error": "no active consented conversation"}
            eyes = {"happy": "happy", "curious": "listening", "sleepy": "sleepy",
                    "cozy": "soft", "proud": "happy"}[args["feeling"]]
            # Rituals own chest pacing and movement. Expressions change eyes only; an in-flight
            # cloud tool keeps its thinking pose until its usual restoration (never after crisis).
            if self.thinking:
                self._eyes = eyes
            else:
                await self.head(eyes=eyes)
            return {"ok": True}
        if name in BACKGROUND_TOOLS:
            # The crisis gate stays first, and local: the person's own words in the arguments are checked here,
            # before anything is forwarded (the cloud runs its own gate again).
            for text in (args.get("said"), args.get("about")):
                if isinstance(text, str) and text and await self.check_utterance_safety(text):
                    return {"ok": False, "error": "stopped", "scheduling": "SILENT"}
            problems = validate_args(REGISTRY[name]["parameters"], args)
            if problems or not self.conversation_consented:
                return {"ok": False, "error": "; ".join(problems) or "no active consented conversation",
                        "scheduling": "SILENT"}
            try:
                res = await self._cloud_tool_thinking(name, args)
            except TimeoutError:
                res = None  # no plan in time: say nothing about it, the conversation simply goes on
            if res is None or (not res.get("crisis") and not res.get("ok")):
                return {"ok": False, "error": (res or {}).get("error") or "not available right now",
                        "scheduling": "SILENT"}
            if res.get("crisis"):
                await self.crisis(Trigger("phrase", "tool_args", None))
                return {"ok": False, "error": "stopped", "scheduling": "SILENT"}
            return {"ok": True, "scheduling": "WHEN_IDLE", **(res.get("result") or {})}
        if name in CLOUD_TOOLS:
            try:
                res = await self._cloud_tool_thinking(name, args)
            except TimeoutError:
                log.info("cloud_tool_timeout", name, after_s=(self.settings.mind_timeout_s
                                                               if name == "ask_mind" else self.think_timeout_s))
                self._tasks.append(asyncio.create_task(self.say(THINK_LATER), name="think-later"))
                return {"ok": False, "error": "taking too long; Kaiku already said it will think about it later"}
            if res is None:
                return {"ok": False, "error": "not available right now"}
            if res.get("crisis"):
                await self.crisis(Trigger("phrase", "tool_args", None))
                return {"ok": False, "error": "stopped"}
            return {"ok": bool(res.get("ok")), **(res.get("result") or {}),
                    **({"error": res["error"]} if res.get("error") else {})}
        if name == "start_activity":  # registry name -> ritual step (steps are ordered)
            name = {"breathe": "start_breathing", "drum": "start_drum"}.get(str(args.get("kind")))
            if name is None:
                return {"ok": False, "error": "activity unavailable on this robot"}
        if name == "send_friend_ping":
            await self.lora.ping()
            return {"ok": True}
        if name == "start_phq9":
            self.state.phq9_due = True  # asked in this ritual's PHQ9 step (spoken/both mode)
            return {"ok": True, "phq9_mode": self.settings.phq9_mode}
        if name in ("start_breathing", "start_drum", "suggest_nudge"):
            step = {"start_breathing": "breathe", "start_drum": "drum", "suggest_nudge": "nudge"}[name]
            return {"ok": self.machine.jump_to(step)}
        if name == "record_dial":
            return {"ok": self.conversation_consented and
                    self.machine.feed(Event("tool", {"name": name, "args": args}))}
        return {"ok": False, "error": f"unknown tool {name}"}

    async def _cloud_tool_thinking(self, name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """Body while a cloud tool (ask_mind, recall, ...) is in flight: eyes `thinking` + a small upward glance
        (the head has no ear command), restored afterwards unless a crisis took over. Raises TimeoutError.
        Background tools (feel) run with no pose: the eyes stay whatever the ritual set (usually `listening`)."""
        timeout = self.settings.mind_timeout_s if name == "ask_mind" else self.think_timeout_s
        if name in BACKGROUND_TOOLS:  # feel: keep listening warmly; the body does not change at all
            return await asyncio.wait_for(
                self.cloud.companion_tool(name, args, getattr(self, "_session_id", None), timeout_s=timeout + 1),
                timeout)
        crisis_n = self._crisis_n
        self.thinking += 1
        await self._cmd("cmd.head", {"eyes": "thinking", "look": {"x": 0.0, "y": 0.3}})
        try:
            return await asyncio.wait_for(
                self.cloud.companion_tool(name, args, getattr(self, "_session_id", None),
                                          timeout_s=timeout + 1),
                timeout)
        finally:
            self.thinking -= 1
            if self.thinking == 0 and self._crisis_n == crisis_n:
                await self._cmd("cmd.head", {"eyes": self._eyes, "look": {"x": 0.0, "y": 0.0}})

    # ================================================================ bus handlers
    def _mark_sim(self, env: Envelope[Any]) -> None:
        if env.sim:
            self._sim_until = time.monotonic() + SIM_WINDOW_S

    async def on_raw(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        if t.type != env.type:  # a valid message on the wrong topic: its payload is not what this topic means
            log.warning("topic_type_mismatch", f"{env.type} on {t.kind}/{t.name}", source=env.source)
            return
        if t.name == "hub/transcript":
            return  # our own echo of her words for the phone (D63): never stored, never fed to anything
        self._mark_sim(env)
        p = env.payload.model_dump()
        name = t.name
        if name == "sensors/face_signs":
            if self.photo_time.running:
                self.photo_time.on_raw(p)  # numbers only; the frames never left the board
            elif self._camera is True and self.conversation_consented:
                await self._camera_window(p)  # a window of this conversation, with her yes to the camera (D61)
            return
        if name == "head/tap" and not self.tap_source.accept(f"{env.source}/{p.get('src')}", time.monotonic()):
            return  # the other board's report of a tap already counted (their clocks cannot be compared)
        if name == "head/ear" and p.get("pressed"):
            # The robot's microphone is closed while its speaker plays, so she cannot talk over Kaiku there: a
            # press of the ear is how she stops what Kaiku is saying. The conversation stays open.
            quiet = getattr(self.voice, "quiet", None)
            if quiet is not None:
                quiet()
        if self._in_session:
            self.store.add_raw(env)
        if self.following and name in ("head/ear", "head/tap", "head/pan", "sensors/ppg"):
            # The head owns the ritual: these feed the follower, never the hub's own steps or the ad-hoc mood
            # (a press outside a dial step carries a stale 1-10 value).
            f = self.follower
            if name == "head/ear":
                self.attention.person_started(datetime.now().astimezone())
                stored = self._in_session
                if p.get("pressed") and self._ask_twice_press():
                    return  # her yes to the activity she asked for: the head goes there itself (D58)
                await self._follow_do(f.on_ear(int(p["value"]), bool(p.get("pressed")), env.ts, time.monotonic()))
                if p.get("pressed"):
                    self._follow_press_opens_talk()
                if self._in_session and not stored:
                    self.store.add_raw(env)  # the press that started the ritual belongs to its record
            elif name == "head/tap":
                if self._game is not None and f.game:
                    if not f.pan_moving:  # the sway motor shakes both tap sensors
                        await self._game.on_tap(p, self)
                else:
                    f.on_tap(int(p["t_ms"]), p.get("force"))
            elif name == "head/pan":
                f.on_pan(bool(p["moving"]))
                self.attention.set_head_pan(p["deg"])
            else:
                f.on_ppg(p["fs_hz"], p["samples"], p.get("t0_ms"), env.quality)
            return
        if name == "head/tap":
            self.machine.feed(Event("tap", p))
            if self.machine.state == "drum" and not getattr(self._drum_step, "playing_game", False):
                # only her own drumming says something about her energy; in Tap it back the tempo is given
                await self.notice(self.drum_feel.add(int(p["t_ms"]), p.get("force")))
        elif name == "head/ear":
            if self.machine.running:
                self.machine.feed(Event("ear", p))
            elif p.get("pressed"):
                self.attention.person_started(datetime.now().astimezone())
                await self.emit("obs.self_report",
                                {"item": "mood", "value": max(1, min(5, int(p["value"]))), "context": "adhoc"})
        elif name == "head/pan":
            self.attention.set_head_pan(p["deg"])
        elif name == "sensors/ppg":
            self.machine.feed(Event("ppg", {**p, "quality": env.quality}))
        elif name == "sensors/distance":
            await self._on_distance(p["cm"])
        elif name == "sensors/light":
            if not self.settings.light_enabled:
                return
            out = self.light.add(p["lux_est"], env.ts, env.quality)
            if self.machine.state in ("greet", "dial"):  # early only: never crowds out breathing/drum events
                await self.notice(light_key(p["lux_est"]))
            if out:
                await self.emit("obs.light_level", out, quality=self.light.closed_quality, ts=self.light.closed_at)
        elif (name == "sensors/button" and p.get("id") == "top") or name == "head/button":
            # One physical button (UNO Q top button, or the Atech head button on the current build):
            # long press >= 2 s = manual safety trigger; short press idle = start a ritual;
            # short presses during a ritual = a dial answer by count (button build) — see perception/presses.py.
            now = time.monotonic()
            short = self.button.was_short_press(p["pressed"], now)
            trig = self.button.update(p["pressed"], now)
            if trig:
                await self.crisis(trig)
            elif short and not self.machine.running:
                self.attention.person_started(datetime.now().astimezone())
                self.start_ritual("button")
            elif short and self.machine.state == "greet":
                self.machine.feed(Event("ear", {"pressed": True}))
            elif short and self.settings.dial_input == "button":
                self.presses.add(now)
                if self._press_task is not None:
                    self._press_task.cancel()
                self._press_task = asyncio.create_task(self._flush_presses())
            elif p["pressed"]:
                self._tasks.append(asyncio.create_task(self._watch_long_press()))
        elif name == "hub/face" and env.source != "hub":  # UNO Q YOLO / sim boxes (our own echo is ignored)
            self.attention.add_face(p, datetime.now().astimezone())
            self._last_face = (time.monotonic(), p)
            await self._follow_track(float(p.get("x_norm") or 0.0))
            self.machine.feed(Event("face", p))

    async def _flush_presses(self) -> None:
        """After `press_window_s` without another press, the count answers the current dial question."""
        await asyncio.sleep(self.presses.window_s + 0.02)
        if self.presses.due(time.monotonic()) and self.machine.running:
            self.machine.feed(Event("ear", self.presses.ear_event()))
        else:
            self.presses.take()

    async def _watch_long_press(self) -> None:
        """Fire the manual trigger while the button is still held (don't wait for release)."""
        await asyncio.sleep(self.button.hold_s + 0.05)
        trig = self.button.poll(time.monotonic())
        if trig:
            await self.crisis(trig)

    async def _on_distance(self, cm: float) -> None:
        now = datetime.now().astimezone()
        was_present = self.presence.present
        arrival = self.presence.update(cm, now)
        if was_present and not self.presence.present and self.machine.running:
            await self.notice("people.away")
        self.attention.set_present(self.presence.present)
        if self.face is not None:
            (self.face.start() if self.presence.present else self.face.stop())
        if not arrival:
            return
        self.state.last_arrival = now
        await self.emit("obs.presence", arrival)  # greeting + ritual offer come from the attention ladder

    def _on_face(self, payload: dict) -> None:
        """Laptop camera (perception/face.py) -> attention + ritual, and raw/hub/face for other listeners."""
        self.attention.add_face(payload, datetime.now().astimezone())
        self._last_face = (time.monotonic(), payload)
        self.machine.feed(Event("face", payload))

        async def pub() -> None:
            with contextlib.suppress(ContractError):
                await self.bus.publish("raw.hub.face", payload)

        asyncio.get_running_loop().create_task(pub())

    # ================================================================ attention ladder
    async def attention_step(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        done = self.state.ritual_done_on(now.date()) and not self.settings.demo_mode
        if self.presence.expire(now):  # the distance stream went silent: unknown is not "here"
            log.warning("presence_stale", "no distance reading; presence dropped")
            self.attention.set_present(False)
            if self.machine.running:
                await self.notice("people.away")
        if self.following:
            await self._follow_do(self.follower.tick(time.monotonic()))
        if self._in_session:  # one look per tick for the engagement summary (numbers only)
            fresh = self._last_face is not None and time.monotonic() - self._last_face[0] <= self.attention.cfg.frame_s
            n = self.attention.face_count(now)
            self.engagement.look(n, self._last_face[1] if fresh and self._last_face else None)
        prev = self.attention.state
        actions = self.attention.tick(now, ritual_done_today=done, ritual_running=self.machine.running)
        if self.machine.running and self.attention.face_count(now) >= 2:
            await self.notice("people.second")
        if self.attention.state != prev:
            log.info("attention", f"{prev} -> {self.attention.state}", faces=self.attention.face_count(now))
        if self.following:
            return  # the head greets and offers by itself (a face or a knock wakes it): no hub reflexes
        for kind, arg in actions:
            if kind == "head":
                await self.head(**arg)
            elif kind == "say":
                line = await self.lines.say_line(arg, self.settings.greeting_language)
                self.trace("said", text=line, by="script" if self.lines.last_source == "text" else "cached_voice")
            elif kind == "offer":
                if time.monotonic() - self._last_ritual_end >= self.settings.ritual_cooldown_s:
                    self.start_ritual("attention")

    async def _attention_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0 / ATTENTION_HZ)
            try:
                await self.attention_step()
            except Exception as e:  # never let the reflex loop die
                log.error("attention_failed", f"{type(e).__name__}: {e}")

    async def on_cmd(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        if str(env.id) in self._seen_cmds:
            return
        self._mark_sim(env)
        c = env.payload
        if c.say:
            await self.on_utterance(c.say)
        if c.start_ritual:
            self.start_ritual("command")
        if c.photo_time:
            self._tasks.append(asyncio.create_task(self.photo_time.run(self), name="photo-time"))
        if c.suggest_nudge:
            self.state.suggest_arm(c.suggest_nudge.arm)
        if c.set_ritual_time:
            self.state.ritual_time = c.set_ritual_time
        if c.phq9_due:
            self.state.phq9_due = True
        if c.clinician_message:
            await self.say(f"A message from your care team: {c.clinician_message.text}")
        if len(self._seen_cmds) > 2000:
            self._seen_cmds.clear()
        self._seen_cmds.add(str(env.id))

    async def on_friendlink_cmd(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        if env.payload.ping:
            await self.lora.ping(env.payload.ping.pattern)

    async def on_obs(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        """Observations from other LOCAL bus producers (e.g. friendlink sim, a kiosk). Safety first.
        Glasses and laptop apps don't use MQTT — they POST to the cloud directly."""
        if env.source == "hub":
            return
        if env.type == "obs.phq9":
            trig = SafetyGate.check_phq9(item9_positive=env.payload.item9_positive)
            if trig:
                await self.crisis(trig)
        if env.home_id != self.settings.home_id:  # the robot's bus home -> the person's record
            env = env.model_copy(update={"home_id": self.settings.home_id})
        self.uplink.enqueue(env)  # relay to the cloud (idempotent by id, so double delivery is harmless)

    async def on_health(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        self.node_health[t.name] = env.payload.model_dump(mode="json")
        if t.name == "head":
            await self._on_head_health(env)

    # ================================================================ follow mode (standalone head, D44)
    async def _on_head_health(self, env: Envelope[Any]) -> None:
        was = self.following
        details = env.payload.details or {}
        if env.payload.status != "down":
            self.head_firmware = "standalone" if details.get("firmware") == "standalone" else "mqtt"
            await self._help_health(details)
        now = time.monotonic()
        if self.following and not was:
            log.info("head_mode", "follow: the head runs the ritual (standalone firmware); the hub records it")
            if self.machine.running:  # never two rituals at once
                await self.end_ritual()
        elif was and not self.following:
            log.info("head_mode", "drive: the head obeys cmd.head; the hub runs the ritual")
            await self._follow_do(self.follower.lost(now, "head no longer runs the standalone firmware"))
        if self.following:
            self._mark_sim(env)
            age = (datetime.now(UTC) - env.ts).total_seconds()
            await self._follow_do(self.follower.on_health(env.payload.status, details, now, age_s=age))

    async def on_sensors_cmd(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        """The standalone head's chimes (cmd.sensors from `head`) mark its step changes exactly."""
        if env.source == "head" and self.following and env.payload.chime:
            self._mark_sim(env)
            await self._follow_do(self.follower.on_chime(env.payload.chime, time.monotonic()))

    async def on_any_head(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        """A head on this broker under another home id: say so once (the usual reason nothing arrives)."""
        if t.home_id != self.bus_home and t.home_id not in self._other_homes and env.payload.status != "down":
            self._other_homes.add(t.home_id)
            log.warning("head_on_other_home", f"a head publishes on home {t.home_id!r}; this hub listens on "
                        f"{self.bus_home!r}. Set KAIKU_HUB_ROBOT_HOME_ID={t.home_id} (or flash the head with this home)")

    async def _follow_do(self, actions: list[tuple]) -> None:
        for a in actions:
            kind = a[0]
            if kind == "begin":
                self._follow_begin(a[1])
                if a[1] == "follow" and self.follower.consented:
                    # The consent rule of drive mode, nothing new: the person started this ritual themselves and
                    # the hub saw the press. Never for a ritual joined mid-way or a start the hub did not see.
                    self._talk_n += 1
                    self._talk_used = True
                    self.accept_conversation()
                    log.info("follow_conversation", "opening: she pressed the ear at the head's greeting")
                else:
                    log.info("follow_conversation", "not open yet: her next press of the ear opens it (D57)")
            elif kind == "end":
                await self._follow_end(a[1], a[2], a[3])
            elif kind == "emit":
                ts = a[4]
                if isinstance(ts, (int, float)):  # "this many seconds ago" (a greeting recorded once answered)
                    ts = datetime.now(UTC) - timedelta(seconds=max(0.0, float(ts)))
                elif ts is not None and abs((datetime.now(UTC) - ts).total_seconds()) > 120:
                    ts = None  # a head clock that far off is not evidence of when the person answered
                await self.emit(a[1], a[2], quality=a[3], ts=ts)
            elif kind == "sensors":
                await self.sensors(**a[1])
            elif kind == "note":
                self.note(a[1], **a[2])
            elif kind == "drum_open":
                self._game_task = asyncio.create_task(self._follow_game(), name="tap-back")
                self._tasks.append(self._game_task)
            elif kind == "game_end":
                await self._end_follow_game(tell_head=False, record=bool(a[1]))
        step = self.follower.step
        if step != self._follow_step_seen:
            self._follow_step_seen = step
            self._follow_step(step)

    async def _follow_spoken_dial(self, args: dict[str, Any]) -> dict[str, Any]:
        """Two ways to answer a dial question on a head that runs its own ritual (D59): the ear, or her words. The
        voice calls `record_dial` for what she said; the hub records it for the question the head is asking NOW
        and tells the head to go on. Never for another question, never outside an open conversation."""
        problems = validate_args(REGISTRY["record_dial"]["parameters"], args)
        if problems:
            return {"ok": False, "error": "; ".join(problems)}
        f = self.follower
        if not self.conversation_consented or not f.active:
            return {"ok": False, "error": "no check-in is open on the robot right now"}
        actions = f.spoken_dial(str(args["item"]), int(args["value"]))
        if actions is None:
            asking = f.step if f.step in follow.DIAL else None
            return {"ok": False, "error": f"the robot is asking about {asking} now" if asking
                    else "the robot is not asking a dial question now"}
        await self._follow_do(actions)
        await self._cmd("cmd.head", {"ritual": "next"}, force=True)
        return {"ok": True, "recorded": args["item"]}

    # ---------------------------------------------------------------- keeping her in view (D62)
    async def _follow_track(self, x: float) -> None:
        """A face frame from the sensors board's camera, `x` from -1 (left edge) to 1 (right edge). When she drifts
        past `edge` the head turns a little toward her: one short pulse (the motor has no position feedback), at
        most every `every_s`, never while the speaker has sound (the two never run together; the head would wait
        and turn late), never in the rhythm game (the head sways with the song). The check that keeps it honest:
        if `max_misses` turns in a row did not bring her nearer the middle (the camera is not on the part that
        turns, or the sign is wrong), it stops for `give_up_s` and says so in the log."""
        st = self.settings
        now = time.monotonic()
        if (not st.track_enabled or not self.following or self.follower.step in (None, "idle")
                or self._game is not None or now < self._track_pause_until or self.speaker_busy):
            return
        if self._track_from is not None and now - self._track_at >= st.track_every_s:
            better = abs(x) <= abs(self._track_from) - 0.08
            self._track_misses = 0 if better else self._track_misses + 1
            self._track_from = None
            if self._track_misses >= st.track_max_misses:
                self._track_misses = 0
                self._track_pause_until = now + st.track_give_up_s
                log.warning("follow_track", f"{st.track_max_misses} turns did not bring the face nearer the middle; "
                            f"paused {st.track_give_up_s:.0f} s (is the camera on the head? [follow_track] sign?)")
                return
        if abs(x) < st.track_edge or now - self._track_at < st.track_every_s:
            return
        self._track_at, self._track_from = now, x
        way = (1 if x > 0 else -1) * st.track_sign
        await self._cmd("cmd.head", {"pan": {"target_deg": 10.0 * way, "speed": st.track_speed}}, force=True)

    # ---------------------------------------------------------------- the camera, once per conversation (D61)
    def _camera_reset(self) -> None:
        self._expr_best, self._expr_n, self._expr_at, self._expr_last = 0.0, 0, 0.0, None
        if self._camera is True:  # the ring goes back to its resting colour when the camera stops counting
            with contextlib.suppress(RuntimeError):
                asyncio.get_running_loop().create_task(self._camera_show(False), name="camera-ring")
        self._camera, self._camera_asked = None, False
        self._camera_answered = asyncio.Event()
        if self._camera_task is not None:
            self._camera_task.cancel()
            self._camera_task = None

    async def _ask_camera_once(self) -> None:
        """When a conversation opens on the robot, the ROBOT asks once whether its camera may be on while they talk,
        in a fixed line, and waits a little for the answer (the voice reports it with `camera_choice`). No answer
        = off. The flag makes a second question in the same conversation impossible, also after a reconnect."""
        if self._camera_asked or not self.conversation_consented:
            return
        self._camera_asked = True
        if not ((self.node_health.get("sensors") or {}).get("details") or {}).get("camera_ok", False):
            return  # no camera to turn on: nothing to ask
        await self.say(CAMERA_LINE)
        with contextlib.suppress(Exception):
            await self.voice.after_speech()  # the wait for her answer starts when the question has been heard
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._camera_answered.wait(), CAMERA_WAIT_S)
        if self._camera is None:
            self.note("camera_not_answered")
        # She gets an answer she can hear and see before anything else is asked: the robot says it, the buzzer
        # sounds for a yes, and the ear ring is green for as long as the camera counts (orange again when it stops).
        await self._camera_show(self._camera is True)
        await self.say(CAMERA_ON_LINE if self._camera is True else CAMERA_OFF_LINE)
        with contextlib.suppress(Exception):
            await self.voice.after_speech()

    async def _camera_choice(self, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args.get("on"), bool):
            return {"ok": False, "error": "on must be true or false"}
        if not self.conversation_consented or not self._camera_asked:
            return {"ok": False, "error": "no conversation is open on the robot right now"}
        on = bool(args["on"])
        first = not self._camera_answered.is_set()  # the answer to the robot's own question: `_ask_camera_once`
        changed, self._camera = self._camera is not on, on  # says and shows it; a later change is shown here
        self._camera_answered.set()
        self.note("camera_choice", on=on)
        if not first and changed:
            await self._camera_show(on)
        if self._camera_task is not None and (not on or self._camera_task.done()):
            self._camera_task.cancel()
            self._camera_task = None
        if on and self._camera_task is None:
            self._camera_task = asyncio.create_task(self._camera_windows(), name="camera-windows")
            self._tasks.append(self._camera_task)
        if on and changed and not self.state.photo_time_done_on(datetime.now().astimezone().date()):
            await self._send_context("Photo time is their once-a-day few seconds in front of your camera to measure "
                                     "themselves (smiles and movement as numbers, no picture). It has not been done "
                                     "today. You may offer it once in this conversation, at a natural moment.")
        return {"ok": True, "camera": "on" if on else "off",
                "note": ("The robot says it itself right now (camera on / camera off): say nothing about it. "
                         if first else "Confirm it in one short sentence. ")
                        + "Do not ask about the camera again in this conversation."}

    async def _camera_show(self, on: bool) -> None:
        """What she can see and hear of the camera's state: the ear ring green while it counts, orange when it
        does not; the buzzer's `ok` for a yes."""
        with contextlib.suppress(Exception):
            await self._cmd("cmd.head", {"color": CAMERA_RING if on else REST_RING}, force=True)
            if on:
                await self.sensors(chime="ok")

    async def _camera_windows(self) -> None:
        """While the conversation is open and she said yes: the sensors board counts face signs in windows, one
        after another (numbers only; the frames never leave the board). Never over a photo time window."""
        window = min(30.0, float(self.settings.camera_window_s))
        while self.conversation_consented and self._camera is True:
            if not self.photo_time.running:
                with contextlib.suppress(Exception):
                    await self.sensors(face_signs_s=window)
            await asyncio.sleep(window + 2.0)

    async def _camera_window(self, raw: dict) -> None:
        """One window of this conversation as `obs.face_signs` (task check_in, device robot): the same shape photo
        time sends, and nothing at all when no face was in view."""
        if not raw.get("coverage"):
            return
        from .rituals.photo_time import observation
        await self.emit("obs.face_signs", {**observation(raw), "task": "check_in"}, quality=0.6)
        await self._expression_cue(raw)

    async def _expression_cue(self, raw: dict) -> None:
        """A visible change in her expression during this conversation, from what the robot's camera can honestly
        count (how much of a window she smiled): `lower` = she smiled earlier in this conversation and for this
        window not at all; `brighter` = she smiled for a good part of it. It is a prompt for ONE gentle question,
        never a conclusion: Kaiku is told in a private context turn, decides whether it fits, and is told not to
        mention her face, the camera or a feeling. At most one every `every_s`, `max_n` per conversation. A
        still, unsmiling face with no earlier smile says nothing (that is how most people look when they listen)."""
        st = self.settings
        smile = raw.get("smile_share")
        if not st.expr_enabled or smile is None or float(raw.get("coverage") or 0) < st.expr_min_coverage:
            return
        smile = float(smile)
        best, self._expr_best = self._expr_best, max(self._expr_best, smile)
        now = time.monotonic()
        if self._expr_n >= st.expr_max_n or now - self._expr_at < st.expr_every_s or self._game is not None:
            return
        kind = ("brighter" if smile >= st.expr_brighter_min
                else "lower" if smile <= st.expr_lower_max and best >= st.expr_earlier_min else None)
        if kind is None or kind == self._expr_last:
            return
        self._expr_n, self._expr_at, self._expr_last = self._expr_n + 1, now, kind
        self.note(f"expression_{kind}", n=self._expr_n)
        await self._send_context(EXPRESSION_CUE[kind])

    # ---------------------------------------------------------------- asking twice (D58)
    async def _ask_twice(self, args: dict[str, Any]) -> dict[str, Any]:
        """First half: she asked Kaiku in words (the voice called `start_activity`). Nothing starts. The head is
        armed for `ASK_TWICE_S`: only a press of its ear in that time starts the activity (`_ask_twice_press`).
        Deterministic from here on: no model decides whether she confirmed."""
        kind = str(args.get("kind"))
        f = self.follower
        if kind not in ASK_TWICE_KINDS:
            return {"ok": False, "error": "this robot can start the breathing or the drums"}
        if not self.conversation_consented or not f.active or f.step in (None, "idle"):
            return {"ok": False, "error": "no check-in is open on the robot right now"}
        if self._episode and self._episode.get("outcome") == "crisis":
            return {"ok": False, "error": "stopped"}
        if kind == "drum" and (self._game is not None or f.step == "drum"):
            return {"ok": False, "error": "the drums are already on"}
        if kind == "breathe" and f.step == "breathe":
            return {"ok": False, "error": "the breathing is already on"}
        self._asked_n += 1
        self._asked = {"kind": kind, "until": time.monotonic() + ASK_TWICE_S, "n": self._asked_n}
        await self._cmd("cmd.head", {"activity": kind}, force=True)
        self.note("activity_asked", kind=kind, step=f.step)
        self._tasks.append(asyncio.create_task(self._ask_twice_expire(self._asked_n), name="ask-twice"))
        return {"ok": True, "started": False, "waiting_for": "a press of your ear", "seconds": int(ASK_TWICE_S)}

    def _ask_twice_press(self) -> bool:
        """Second half: a press of the ear while an ask is open is her yes. The head goes straight to that step by
        itself (it was armed); the follower is told to expect it. True = this press was that yes and nothing else
        (not a dial answer, not a skip)."""
        asked, self._asked = self._asked, None
        if asked is None or time.monotonic() > asked["until"]:
            return False
        self.follower.asked = asked["kind"]
        self.note("activity_confirmed", kind=asked["kind"])
        return True

    async def _ask_twice_expire(self, n: int) -> None:
        await asyncio.sleep(ASK_TWICE_S + 0.5)
        asked = self._asked
        if asked is None or asked["n"] != n:
            return  # she pressed, or asked for something else
        self._asked = None
        with contextlib.suppress(Exception):
            await self._cmd("cmd.head", {"activity": "none"}, force=True)
        self.note("activity_not_confirmed", kind=asked["kind"])
        await self._send_context(f"The ear was not pressed, so {ASK_TWICE_KINDS[asked['kind']]} did not start. "
                                 "Say so in a few words. They can ask again.")

    def _follow_press_opens_talk(self) -> None:
        """The one rule for when the robot listens while the head runs its own ritual (D57): the first press of the
        ear the hub sees in a ritual opens the conversation, whatever step the head is in (the greeting, or later
        when the hub missed the greeting or joined mid-way). It stays open until that ritual ends. One conversation
        per ritual: after a crisis, or after she asked to stop talking, a press is only a press."""
        f, ep = self.follower, self._episode
        if (not f.active or ep is None or f.step in (None, "idle") or self.conversation_consented
                or ep.get("outcome") == "crisis" or self._talk_used or not self.voice.wants_session):
            return
        f.consented = True
        self._talk_n += 1
        self._talk_used = True
        self.accept_conversation()
        log.info("follow_conversation", f"opening: she pressed the ear (head in {f.step})")
        line = follow.STEP_LINES.get(f.step or "")
        if line and f.step not in ("drum", "done"):
            self._tasks.append(asyncio.create_task(self._follow_say(f.step, line), name="follow-say"))

    def _follow_step(self, step: str | None) -> None:
        """The head entered a step of its own ritual. At its greeting Kaiku says the invitation (what a press will
        turn on), in the cached voice, at most every `[hub] follow_offer_every_s`. While a conversation the person
        started is open, Kaiku says the usual short line for the step through the head, and she can answer.
        The drum step's words belong to `_follow_game`; the goodbye to `_follow_end`."""
        f = self.follower
        if step == "greet" and not f.active:
            now = time.monotonic()
            if self.voice.wants_session and now - self._follow_offer_at >= self.settings.follow_offer_every_s:
                self._follow_offer_at = now
                self._tasks.append(asyncio.create_task(self.say(steps.OFFER_LINE), name="follow-offer"))
            return
        line = follow.STEP_LINES.get(step or "")
        if line and step not in ("drum", "done") and f.active and self.conversation_consented:
            self._tasks.append(asyncio.create_task(self._follow_say(step, line), name="follow-say"))

    async def _follow_say(self, step: str | None, line: str) -> None:
        """One step line, once the conversation is open (the press that opens it also moves the head on), and only
        if the head is still in that step."""
        opening = self._live_open_task
        if opening is not None and not opening.done():
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(opening), 8.0 + CAMERA_WAIT_S)  # incl. the camera question
        with contextlib.suppress(Exception):
            await self.voice.after_speech()  # a line is checked when it can be said, not when it was thought of:
        if self.follower.step == step and self.follower.active and self.conversation_consented:   # she may have
            await self.say(line)                                                                  # moved on

    async def _follow_game(self) -> None:
        """Tap it back while FOLLOWING a head that runs its own ritual (D51). The head is in its drum step; when a
        song can play, the hub holds it there (`cmd.head {drum: hold}`), runs the game with the head's taps, and
        lets it go (`drum: end`). No song (music off, over the spend cap, no key): nothing is sent and the hub
        simply follows the head's own free drumming, as before."""
        cfg, f = self.settings.tap_back, self.follower

        async def free() -> None:  # the head's own free drumming: Kaiku only says so, in an open conversation
            if f.step == "drum" and f.active and self.conversation_consented:
                await self.say(follow.STEP_LINES["drum"])

        if cfg.mode == "free":
            await free()
            return
        if not self._head_can_hold():
            log.warning("tap_back", "this head's firmware cannot lend its drum step (no drum_held in health/head): "
                        "its own free drumming is followed, no game")
            await free()
            return
        try:
            await self.music.start(f._dial.get("mood"))
            if not (cfg.mode == "tap_back" or self.music.can_play_songs) or f.step != "drum" or not f.active:
                await self.music.stop()
                await free()
                return
            game = tap_back.Game(cfg, sway=True, refractory_ms=self.settings.tap_refractory_ms,
                                 force_max_g=self.settings.tap_force_max_g, hold=True)
            self._game = game
            f.game_started()
            log.info("tap_back", "the hub runs the drum phase of the head's ritual", levels=[lv.bpm for lv in game.levels])
            await game.begin(self)
            while f.step == "drum" and f.active and self._game is game:
                await asyncio.sleep(max(0.01, min(0.05, game.next_deadline() - time.monotonic())))
                state = await game.tick(self)
                f.game_levels = sum(any(t.measured for t in r.tries) for r in game.results)
                if state == "fallback":  # the song never came: her free drumming on the head's own timer from here
                    f.game = False       # (no `hold` is sent any more; the head takes its timer back by itself)
                    self._game = None
                    await self.music.stop()
                    await game.leave(self)
                    log.info("tap_back", "no song: following the head's free drumming")
                    await self.say(tap_back.FALLBACK_LINE)  # she was promised a song: the same words as drive mode
                    return
                if state == "done":
                    break
            if self._game is game:
                await self._end_follow_game(tell_head=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # the game must never break the recording of the head's ritual
            log.error("tap_back_failed", f"{type(e).__name__}: {e}", exc_info=True)
            await self._end_follow_game(tell_head=True)

    async def _end_follow_game(self, *, tell_head: bool, record: bool = True) -> None:
        """The game is over (it finished, the head left its drum step, a crisis, the hub stops): quiet, record what
        was played, and give the head its ritual back."""
        game, self._game = self._game, None
        task, self._game_task = self._game_task, None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
        if game is None:
            return
        with contextlib.suppress(Exception):
            await self.music.stop()
        with contextlib.suppress(Exception):
            await game.leave(self)  # a microphone the game closed is open again however it ended
        out = game.payload()
        if out is not None and record:
            await self.emit("obs.tap_back", out[0], quality=out[1])
            self.follower.game_levels = max(1, self.follower.game_levels)
        if tell_head:
            await self._cmd("cmd.head", {"drum": "end", "pan_mode": "still"}, force=True)

    def _follow_begin(self, reason: str) -> None:
        log.info("ritual_start", reason, head_step=self.follower.step)
        self._talk_used = False
        self._camera_reset()
        self._clear_help()
        self._episode = {"id": str(uuid4()), "start": datetime.now(UTC), "outcome": "completed", "tools_used": []}
        self.ritual_reason = reason
        self.engagement.reset()
        self._notes = {}
        self.store.begin(self._episode["id"], reason, home_id=self.settings.home_id, sim=self.is_sim)
        self._in_session = True

    async def _follow_end(self, outcome: str, consented: bool, dial: dict[str, int]) -> None:
        episode, self._episode = self._episode, None
        if dial:  # same bookkeeping as the hub's own dial step (today's answers, yesterday's suggestion outcome)
            nudge = self.state.record_dial(datetime.now().astimezone().date(), mood=dial.get("mood"),
                                           energy=dial.get("energy"), sleep=dial.get("sleep"))
            if nudge:
                await self.emit("obs.nudge_outcome", nudge)
        self._asked = None
        self._camera_reset()
        talked, self.conversation_consented = self.conversation_consented, False
        if self._live_open_task and not self._live_open_task.done():
            self._live_open_task.cancel()
        if episode:
            episode.pop("_explicit_outcome", None)
            episode["outcome"] = "crisis" if episode["outcome"] == "crisis" else outcome
            if episode["outcome"] == "crisis":
                episode.pop("open_thread", None)
            transcript = getattr(self.voice, "transcript", None)
            keep = self.settings.hub_transcripts and consented and episode["outcome"] != "crisis"
            self.episodes.enqueue(EpisodeIn(home_id=self.settings.home_id, surface="robot", intent="ritual",
                                            end=datetime.now(UTC), transcript=transcript if keep else None, **episode))
            outcome = episode["outcome"]
        if hasattr(self.voice, "transcript"):
            self.voice.transcript = []
        if self.voice.wants_session:  # the conversation ends with the head's ritual, whatever ended it
            self._tasks.append(asyncio.create_task(self._follow_close_talk(talked and outcome == "completed"),
                                                   name="follow-talk-close"))
        self._close_session(episode["id"] if episode else None, outcome, consented)
        self.ritual_reason = ""
        self._last_ritual_end = time.monotonic()
        log.info("ritual_done", outcome, mode="follow")
        if outcome == "completed":
            self.state.mark_ritual_done(datetime.now().astimezone().date())

    async def _follow_close_talk(self, goodbye: bool) -> None:
        """Close the conversation of a followed ritual. After a whole ritual Kaiku says goodbye first: the
        microphone is closed at once, the session when the words have been heard (a few seconds at most)."""
        n = self._talk_n
        try:
            if goodbye and self.voice.in_session:
                self.voice.listen(False)
                line = follow.STEP_LINES["done"]
                await self.say(line)
                t0 = time.monotonic()
                await asyncio.sleep(max(1.0, tap_back.words(line) * self.settings.tap_back.word_s))
                while self.speaker_busy and time.monotonic() - t0 < 8.0:
                    await asyncio.sleep(0.1)
        except Exception as e:
            log.warning("follow_goodbye_failed", f"{type(e).__name__}: {e}")
        if self._talk_n == n and not self.conversation_consented:  # never a newer conversation
            await self.voice.close_session()

    # ================================================================ lifecycle
    def _details(self) -> dict[str, Any]:
        return {
            "ritual": f"head:{self.follower.step or 'unknown'}" if self.following else self.machine.state,
            "head_mode": "follow" if self.following else "drive",
            "head_cmds_held": self.head_cmds_held,
            "uplink_queue": self.uplink.size(),
            "uplink_lag_s": self.uplink.lag_s(),
            "uplink_error": self.uplink.last_error,
            "voice": self.voice.name,
            "music": self.music.name,
            "music_out": self.settings.music_out,
            "voice_audio": getattr(self.voice, "audio_name", "none"),
            "mic_source": self.head_audio.mic_source,  # "phone" while a phone beside the robot sends its microphone
            # open = the robot is listening; closed + a head that runs its own ritual = a press of its ear opens it
            "talk": "open" if self.conversation_consented and self.voice.in_session
                    else "opening" if self.conversation_consented else "closed",
            "cloud": bool(self.settings.cloud_url),
            "episodes_queue": self.episodes.size(),
            "store": "off" if self.settings.store_path is None else ("error" if self.store.error else "ok"),
        }

    def _health_snapshot(self) -> tuple[dict[str, dict], int, float | None]:
        return dict(self.node_health), self.uplink.size(), self.uplink.lag_s()

    async def _republish_cloud_cmd(self, env: Envelope[Any]) -> None:
        await self.on_cmd(None, env)  # apply locally before acknowledging cloud delivery
        await self.cloud.ack_command(str(env.id))

    async def _ritual_time_loop(self) -> None:
        """At the configured time, Kaiku invites (never forces) the ritual if not done today."""
        last_invite: str | None = None
        while True:
            await asyncio.sleep(20)
            hhmm = self.state.ritual_time
            now = datetime.now().astimezone()
            if hhmm and now.strftime("%H:%M") == hhmm and last_invite != now.date().isoformat():
                if not self.machine.running and not self.state.ritual_done_on(now.date()):
                    last_invite = now.date().isoformat()
                    await self.head(eyes="wide", purr={"ms": 400})
                    await self.say("Good morning. I'm here whenever you're ready.")

    async def start(self) -> None:
        b = self.bus
        b.on("raw/#", self.on_raw)
        b.on("cmd/hub", self.on_cmd)
        b.on("cmd/friendlink", self.on_friendlink_cmd)
        b.on("obs/#", self.on_obs)
        b.on("health/+", self.on_health)
        b.on("cmd/sensors", self.on_sensors_cmd)
        b.on("health/head", self.on_any_head, home_id="+")
        b.on_audio("mic", self.head_audio.on_mic_frame)  # PCM, only while a conversation holds the microphone open
        b.on_audio("mic", self.head_audio.on_phone_frame, node="phone")  # a phone beside the robot as its ear (D56)
        await b.__aenter__()
        await self.voice.start(self.on_utterance, self.on_tool)
        # Every fixed line Kaiku can say in the cached voice, fetched now: an unrendered line takes longer than the
        # 3 s a spoken line may wait, and was then never said (the goodbye and the invitation, 2026-11-15).
        fixed = [steps.OFFER_LINE, *follow.STEP_LINES.values(), *tap_back.BAND_LINE.values(), tap_back.AGAIN_LINE,
                 tap_back.NO_TAPS_LINE, tap_back.MOVE_ON_LINE, tap_back.FALLBACK_LINE,
                 "Good morning. I'm here whenever you're ready.", CAMERA_LINE, CAMERA_ON_LINE, CAMERA_OFF_LINE]
        self._tasks.append(asyncio.create_task(self.lines.prewarm(fixed, self.settings.language), name="voice-prewarm"))
        await self.lora.start()
        if self.atech:
            await self.atech.start()
        self._tasks += [
            asyncio.create_task(self.uplink.run(), name="uplink"),
            asyncio.create_task(self.episodes.run(), name="episodes"),
            asyncio.create_task(self.cloud.run(self._republish_cloud_cmd, self._health_snapshot), name="cloudlink"),
            asyncio.create_task(self._ritual_time_loop(), name="ritual-time"),
            asyncio.create_task(self._attention_loop(), name="attention"),
        ]
        if self.unoq_faces:
            self._tasks.append(asyncio.create_task(self.unoq_faces.start(), name="unoq-faces"))
        log.info("hub_started", f"home={self.settings.home_id}", head=self.settings.head, sensors=self.settings.sensors,
                 faces=self.settings.face_source if (self.face or self.unoq_faces) else "off",
                 voice=self.voice.name, music=self.music.name, cloud=self.settings.cloud_url or "offline")

    async def stop(self) -> None:
        await self.end_ritual()
        if self._game is not None:  # stopped mid-game: keep what was played and give the head its step back
            await self._end_follow_game(tell_head=True)
        if self.follower.active:  # stopped while the head is mid-ritual: close the record honestly
            await self._follow_do(self.follower.abort(time.monotonic(), "ended_early", "hub stopped"))
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self.face:
            self.face.stop()
        if self.unoq_faces:
            with contextlib.suppress(Exception):
                await self.unoq_faces.stop()
        for closer in (self.voice.stop, self.music.stop, self.lora.stop):
            with contextlib.suppress(Exception):
                await closer()
        if self.atech:
            await self.atech.stop()
        await self.bus.__aexit__(None, None, None)
        if self._in_session:  # stopped mid-ritual: close the stored session rather than leave it open
            self._in_session = False
            self.store.end(outcome="ended_early", sim=self.is_sim, summary={"notes": self._notes})
        self.store.flush()

    async def run(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        await self.start()
        try:
            await stop.wait()
        finally:
            await self.stop()


async def _main(args: argparse.Namespace) -> None:
    hub = Hub()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    if args.start:
        async def kick() -> None:
            await hub.bus.connected.wait()
            hub.start_ritual("cli")

        loop.create_task(kick())
    await hub.run(stop)


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Kaiku hub")
    ap.add_argument("--start", action="store_true", help="start a ritual immediately")
    asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    main()
