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
import signal
import sys
import time
from datetime import datetime
from typing import Any

import httpx
from kaiku_contracts import ContractError, Envelope, ParsedTopic, make
from kaiku_contracts.config import load_dotenv
from kaiku_contracts.jlog import get_logger

from . import __version__
from .bus import Bus
from .cloudlink import CloudLink, local_nudge
from .devices.atech_adapter import AtechAdapter
from .devices.lora_serial import LoraSerialAdapter
from .live import Music, Voice, make_music, make_voice
from .perception import face
from .perception.light import LightAggregator
from .perception.presence import PresenceTracker
from .rituals import Event, RitualMachine, default_steps
from .safety import ButtonLongPress, CrisisScript, SafetyGate, Trigger
from .settings import Settings
from .state import HubState
from .uplink import Uplink

log = get_logger("hub")

SIM_WINDOW_S = 60.0
CRISIS_DEDUPE_S = 60.0


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
        self.voice = voice or make_voice(s.voice, model_id=s.gemini_live_model, language=s.language,
                                         read_stdin=read_stdin)
        self.music = music or make_music(s.music, model_id=s.lyria_model, bpm_min=s.bpm_min, bpm_max=s.bpm_max)
        self.bus = Bus("hub", home_id=s.home_id, version=__version__, details=self._details)
        self.uplink = Uplink(url=s.cloud_url, token=s.home_token, queue_path=s.queue_path,
                             batch_s=s.uplink_batch_s, max_batch=s.uplink_max_batch, timeout_s=s.uplink_timeout_s,
                             transport=transport)
        self.cloud = CloudLink(url=s.cloud_url, home_id=s.home_id, token=s.home_token, transport=transport)
        self.gate = SafetyGate.from_file()
        self.script = CrisisScript.from_file()
        self.button = ButtonLongPress(hold_s=2.0)
        self.presence = PresenceTracker(s.presence_near_cm, s.first_of_day_after_h, last_arrival=self.state.last_arrival)
        self.light = LightAggregator(s.light_window_min)
        self.machine = RitualMachine(self, default_steps(s), step_timeout_s=s.step_timeout_s)
        self.lora = LoraSerialAdapter(self.emit)
        self.atech = AtechAdapter() if s.head == "atech" else None
        self.face = face.FaceTracker(self._on_face) if face.available() else None
        self.node_health: dict[str, dict] = {}
        self._sim_until = 0.0
        self._last_ritual_end = -1e9
        self._last_crisis: dict[str, float] = {}
        self._seen_cmds: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self.emitted: list[Envelope[Any]] = []  # in-process tap for tests/debugging (bounded)

    # ================================================================ RitualContext
    async def say(self, text: str) -> None:
        try:
            await self.voice.say(text)
        except Exception as e:
            log.warning("voice_failed", str(e))

    async def head(self, **cmd: Any) -> None:
        await self._cmd("cmd.head", cmd)

    async def sensors(self, **cmd: Any) -> None:
        await self._cmd("cmd.sensors", cmd)

    async def _cmd(self, type_: str, payload: dict) -> None:
        try:
            await self.bus.publish(type_, payload)
        except ContractError as e:
            log.error("bad_command", str(e)[:300], type=type_)

    @property
    def is_sim(self) -> bool:
        return time.monotonic() < self._sim_until

    async def emit(self, type_: str, payload: dict, quality: float | None = None) -> Envelope[Any] | None:
        """Every observation goes through here: validate -> bus -> uplink queue."""
        try:
            env = make(type_, payload, source="hub", home_id=self.settings.home_id, quality=quality, sim=self.is_sim)
        except ContractError as e:
            log.error("emit_invalid", str(e)[:300], type=type_)
            return None
        await self.bus.publish_env(env)
        self.uplink.enqueue(env)
        self.emitted.append(env)
        del self.emitted[:-500]
        log.info("obs", type_, **{k: v for k, v in payload.items() if isinstance(v, (int, float, str, bool))})
        if type_ == "obs.phq9":  # safety gate on PHQ-9 answers, whichever step produced them
            trig = SafetyGate.check_phq9(item9_positive=env.payload.item9_positive)
            if trig:
                self._tasks.append(asyncio.create_task(self.crisis(trig), name="crisis"))
        return env

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
        if self.machine.running:
            return False
        log.info("ritual_start", reason)
        task = self.machine.start()
        if task:
            task.add_done_callback(self._ritual_done)
        return task is not None

    def _ritual_done(self, task: asyncio.Task) -> None:
        self._last_ritual_end = time.monotonic()
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
        log.warning("safety_trigger", trigger.kind, matched=trigger.detail, lang=trigger.language)
        # 1. stop the ritual and any generated audio
        await self.machine.abort()
        with contextlib.suppress(Exception):
            await self.music.stop()
        with contextlib.suppress(Exception):
            await self.voice.interrupt()
        # 2. calm body language
        await self.head(eyes="soft", chest="off", pan_mode="still")
        # 3. scripted message, verbatim (+ helpline numbers always visible in logs/terminal)
        text = self.script.text(self.settings.language)
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

    async def on_utterance(self, text: str) -> None:
        """All user speech/text enters here. Safety gate runs FIRST."""
        trig = self.gate.check_text(text)
        if trig:
            await self.crisis(trig)
            return
        cmd = text.strip().lower()
        if cmd in ("start", "aloita"):
            self.start_ritual("text")
        elif cmd in ("skip", "ohita"):
            self.machine.feed(Event("skip"))
        elif self.machine.running:
            self.machine.feed(Event("utterance", {"text": text}))

    async def on_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Voice-model tool calls. Requests only; the hub decides."""
        if name == "send_friend_ping":
            await self.lora.ping()
            return {"ok": True}
        if name == "end_ritual":
            self.machine.feed(Event("skip"))
            return {"ok": True}
        if name == "start_phq9":
            self.state.phq9_due = True  # asked in this ritual's PHQ9 step (spoken/both mode)
            return {"ok": True, "phq9_mode": self.settings.phq9_mode}
        if name in ("start_breathing", "start_drum", "suggest_nudge"):
            self.machine.feed(Event("skip"))  # advance to the requested step (steps are ordered)
            return {"ok": True}
        if name == "record_dial":
            self.machine.feed(Event("tool", {"name": name, "args": args}))
            return {"ok": True}
        return {"ok": False, "error": f"unknown tool {name}"}

    # ================================================================ bus handlers
    def _mark_sim(self, env: Envelope[Any]) -> None:
        if env.sim:
            self._sim_until = time.monotonic() + SIM_WINDOW_S

    async def on_raw(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        self._mark_sim(env)
        p = env.payload.model_dump()
        name = t.name
        if name == "head/tap":
            self.machine.feed(Event("tap", p))
        elif name == "head/ear":
            if self.machine.running:
                self.machine.feed(Event("ear", p))
            elif p.get("pressed"):
                await self.emit("obs.self_report",
                                {"item": "mood", "value": max(1, min(5, int(p["value"]))), "context": "adhoc"})
        elif name == "sensors/ppg":
            self.machine.feed(Event("ppg", p))
        elif name == "sensors/distance":
            await self._on_distance(p["cm"])
        elif name == "sensors/light":
            out = self.light.add(p["lux_est"], datetime.now().astimezone())
            if out:
                await self.emit("obs.light_level", out)
        elif name == "sensors/button" and p.get("id") == "top":
            now = time.monotonic()
            short = self.button.was_short_press(p["pressed"], now)
            trig = self.button.update(p["pressed"], now)
            if trig:
                await self.crisis(trig)
            elif short and not self.machine.running:
                self.start_ritual("button")
            elif p["pressed"]:
                self._tasks.append(asyncio.create_task(self._watch_long_press()))
        elif name == "hub/face":
            self.machine.feed(Event("face", p))

    async def _watch_long_press(self) -> None:
        """Fire the manual trigger while the button is still held (don't wait for release)."""
        await asyncio.sleep(self.button.hold_s + 0.05)
        trig = self.button.poll(time.monotonic())
        if trig:
            await self.crisis(trig)

    async def _on_distance(self, cm: float) -> None:
        now = datetime.now().astimezone()
        arrival = self.presence.update(cm, now)
        if self.face is not None:
            (self.face.start() if self.presence.present else self.face.stop())
        if not arrival:
            return
        self.state.last_arrival = now
        await self.emit("obs.presence", arrival)
        cooled = time.monotonic() - self._last_ritual_end >= self.settings.ritual_cooldown_s
        today_done = self.state.ritual_done_on(now.date())
        if cooled and (arrival["first_of_day"] or (self.settings.demo_mode or not today_done)):
            self.start_ritual("presence")

    def _on_face(self, payload: dict) -> None:
        async def pub() -> None:
            with contextlib.suppress(ContractError):
                await self.bus.publish("raw.hub.face", payload)
            self.machine.feed(Event("face", payload))

        asyncio.get_running_loop().create_task(pub())

    async def on_cmd(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        if str(env.id) in self._seen_cmds:
            return
        self._seen_cmds.add(str(env.id))
        if len(self._seen_cmds) > 2000:
            self._seen_cmds.clear()
        self._mark_sim(env)
        c = env.payload
        if c.say:
            await self.on_utterance(c.say)
        if c.start_ritual:
            self.start_ritual("command")
        if c.suggest_nudge:
            self.state.suggest_arm(c.suggest_nudge.arm)
        if c.set_ritual_time:
            self.state.ritual_time = c.set_ritual_time
        if c.phq9_due:
            self.state.phq9_due = True
        if c.clinician_message:
            await self.say(f"A message from your care team: {c.clinician_message.text}")

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
        self.uplink.enqueue(env)  # relay to the cloud (idempotent by id, so double delivery is harmless)

    async def on_health(self, t: ParsedTopic, env: Envelope[Any]) -> None:
        self.node_health[t.name] = env.payload.model_dump(mode="json")

    # ================================================================ lifecycle
    def _details(self) -> dict[str, Any]:
        return {
            "ritual": self.machine.state,
            "uplink_queue": self.uplink.size(),
            "uplink_lag_s": self.uplink.lag_s(),
            "uplink_error": self.uplink.last_error,
            "voice": self.voice.name,
            "music": self.music.name,
            "cloud": bool(self.settings.cloud_url),
        }

    def _health_snapshot(self) -> tuple[dict[str, dict], int, float | None]:
        return dict(self.node_health), self.uplink.size(), self.uplink.lag_s()

    async def _republish_cloud_cmd(self, env: Envelope[Any]) -> None:
        await self.bus.publish_env(env)  # comes back to us via cmd/hub (single code path)

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
        await b.__aenter__()
        await self.voice.start(self.on_utterance, self.on_tool)
        await self.lora.start()
        if self.atech:
            await self.atech.start()
        self._tasks += [
            asyncio.create_task(self.uplink.run(), name="uplink"),
            asyncio.create_task(self.cloud.run(self._republish_cloud_cmd, self._health_snapshot), name="cloudlink"),
            asyncio.create_task(self._ritual_time_loop(), name="ritual-time"),
        ]
        log.info("hub_started", f"home={self.settings.home_id}", head=self.settings.head, sensors=self.settings.sensors,
                 voice=self.voice.name, music=self.music.name, cloud=self.settings.cloud_url or "offline")

    async def stop(self) -> None:
        await self.machine.abort()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self.face:
            self.face.stop()
        for closer in (self.voice.stop, self.music.stop, self.lora.stop):
            with contextlib.suppress(Exception):
                await closer()
        if self.atech:
            await self.atech.stop()
        await self.bus.__aexit__(None, None, None)

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
