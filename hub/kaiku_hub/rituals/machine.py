"""Explicit, testable ritual state machine.

Each step: applies(ctx)? -> enter(ctx) -> handle(event, ctx) ... -> on_deadline(ctx) -> exit(ctx, status).
- applies(): False = step is not part of today's ritual (no obs.ritual emitted), e.g. PHQ9 when not due.
- handle() returns a status ("completed"/"skipped") to finish early, or None to keep going.
- deadline(): step may end earlier than its timeout (e.g. drum idle). on_deadline() may return None to
  continue into a next phase (it must move deadline() forward, e.g. drum -> post-activity mood dial).
  Everything is capped by step_timeout_s, which calls on_timeout() (sync, no I/O).
- step.stop_ritual = True ends the ritual after this step (e.g. PHQ-9 item 9 positive -> safety path).
- Event("skip") skips the current step; abort() cancels the ritual (safety) and emits "aborted".
Every step that applies emits obs.ritual started + completed|skipped|aborted with duration_s.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from kaiku_contracts.jlog import get_logger

log = get_logger("hub")

Status = Literal["completed", "skipped", "aborted"]


@dataclass
class Event:
    kind: str  # tap | ear | ppg | face | utterance | skip | tool
    data: dict[str, Any] = field(default_factory=dict)


class RitualContext(Protocol):
    """What steps may do. The hub implements it; tests use a fake."""

    settings: Any
    state: Any
    music: Any

    async def say(self, text: str) -> None: ...
    async def head(self, **cmd: Any) -> None: ...
    async def sensors(self, **cmd: Any) -> None: ...
    async def emit(self, type_: str, payload: dict, quality: float | None = None) -> Any: ...
    async def get_nudge(self) -> tuple[str, str]: ...


class Step:
    name: str = "step"
    timeout_s: float = 30.0

    def __init__(self, timeout_s: float | None = None):
        if timeout_s is not None:
            self.timeout_s = timeout_s
        self.t0 = 0.0
        self.stop_ritual = False

    def applies(self, ctx: RitualContext) -> bool:
        return True

    def deadline(self) -> float:
        return self.t0 + self.timeout_s

    async def enter(self, ctx: RitualContext) -> None:
        return None

    async def handle(self, event: Event, ctx: RitualContext) -> Status | None:
        return None

    def on_timeout(self) -> Status:
        return "completed"

    async def on_deadline(self, ctx: RitualContext) -> Status | None:
        """Soft deadline reached. Return a status to finish, or None after moving deadline() forward."""
        return self.on_timeout()

    async def exit(self, ctx: RitualContext, status: Status) -> None:
        return None


class RitualMachine:
    def __init__(self, ctx: RitualContext, steps: list[Step], step_timeout_s: float = 120.0):
        self.ctx = ctx
        self.steps = steps
        self.step_timeout_s = step_timeout_s
        self.state = "idle"
        self.results: dict[str, Status] = {}
        self._queue: asyncio.Queue[Event] | None = None
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def feed(self, event: Event) -> bool:
        if self._queue is None:
            return False
        self._queue.put_nowait(event)
        return True

    def start(self) -> asyncio.Task | None:
        if self.running:
            return None
        self._task = asyncio.create_task(self.run(), name="ritual")
        return self._task

    async def abort(self) -> None:
        task = self._task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def run(self) -> dict[str, Status]:
        self.results = {}
        try:
            for step in self.steps:
                step.stop_ritual = False
                if not step.applies(self.ctx):
                    continue
                self.results[step.name] = await self._run_step(step)
                if step.stop_ritual:
                    log.info("ritual_stopped", f"stopped after {step.name}")
                    break
        finally:
            self.state = "idle"
            self._queue = None
        return self.results

    async def _run_step(self, step: Step) -> Status:
        self.state = step.name
        self._queue = q = asyncio.Queue()
        step.t0 = time.monotonic()
        hard_deadline = step.t0 + self.step_timeout_s
        await self.ctx.emit("obs.ritual", {"step": step.name, "status": "started"})
        status: Status
        try:
            await step.enter(self.ctx)
            while True:
                now = time.monotonic()
                if now >= hard_deadline:
                    status = step.on_timeout()
                    break
                if step.deadline() <= now:
                    result = await step.on_deadline(self.ctx)
                    if result:
                        status = result
                        break
                    if step.deadline() <= time.monotonic():  # step didn't move its deadline: end it
                        status = step.on_timeout()
                        break
                    continue
                remaining = min(step.deadline(), hard_deadline) - now
                try:
                    ev = await asyncio.wait_for(q.get(), remaining)
                except TimeoutError:
                    continue  # re-check deadline (steps may move it)
                if ev.kind == "skip":
                    status = "skipped"
                    break
                result = await step.handle(ev, self.ctx)
                if result:
                    status = result
                    break
            await step.exit(self.ctx, status)
        except asyncio.CancelledError:
            await self._finish(step, "aborted")
            try:
                await step.exit(self.ctx, "aborted")
            except Exception:
                log.error("step_exit_failed", step.name, exc_info=True)
            raise
        except Exception as e:  # a broken step must not kill the hub: skip it, keep going
            log.error("step_failed", f"{step.name}: {type(e).__name__}: {e}", exc_info=True)
            status = "skipped"
        await self._finish(step, status)
        return status

    async def _finish(self, step: Step, status: Status) -> None:
        dur = round(time.monotonic() - step.t0, 1)
        await self.ctx.emit("obs.ritual", {"step": step.name, "status": status, "duration_s": dur})
