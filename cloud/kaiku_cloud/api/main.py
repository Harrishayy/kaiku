"""Kaiku cloud API (FastAPI). Local: `make cloud-local` (uvicorn kaiku_cloud.api.main:app). Modal: cloud/app.py.

Routes are listed in docs/plans/01-foundation.md §6.7 (ground truth for shapes: kaiku_contracts.api). The static web app (Next.js export) is mounted at `/` last,
so /v1/* and /healthz always win.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from kaiku_contracts import SCHEMA_VERSION, UPLINKABLE, ContractError, make, validate
from kaiku_contracts.api import (
    ActionRequest,
    ActionResult,
    CommandsResponse,
    CompanionSessionRequest,
    CompanionSessionResponse,
    CompanionToolCall,
    CompanionToolResult,
    Consensus,
    CriteriaPreview,
    CriteriaResponse,
    CriteriaUpdate,
    DeletedResponse,
    EpisodeIn,
    EpisodeResult,
    EvalResult,
    EventsResult,
    HealthOverview,
    Healthz,
    LiveEventsResponse,
    MemoriesResponse,
    MemorySettings,
    MeResponse,
    NodeHealthReport,
    NudgeResponse,
    PatientsResponse,
    Phq9History,
    TimelineResponse,
    VoiceLang,
    VoiceLinesResponse,
)
from kaiku_contracts.jlog import get_logger

from .. import service, voice
from ..jobs import nightly
from ..mind import memory as mind_memory
from ..mind import session as mind
from ..settings import VERSION, Settings
from ..store.db import Store

MAX_BATCH = 500
log = get_logger("cloud")


def norm_ts(ts: str | None) -> str | None:
    """Normalise a client `since` to the stored format (UTC, ms, Z) so string comparison is correct."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"invalid timestamp {ts!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def create_app(settings: Settings | None = None, *, eval_runner: Callable[..., EvalResult] | None = None,
               after_write: Callable[[], None] | None = None) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.db_path)
    app = FastAPI(title="Kaiku cloud", version=VERSION)
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    if after_write is not None:  # e.g. Modal Volume commit after mutating requests
        commit_lock = threading.Lock()

        def _commit() -> None:
            with commit_lock:
                try:
                    after_write()
                except Exception as e:
                    log.warning("after_write_failed", str(e))

        @app.middleware("http")
        async def _after_write(request: Request, call_next):
            response = await call_next(request)
            if request.method in ("POST", "PUT", "DELETE") and response.status_code < 400:
                asyncio.get_running_loop().run_in_executor(None, _commit)
            return response

    # ------------------------------------------------------------------ auth helpers
    def bearer(authorization: str | None) -> str | None:
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return None

    def require_home_token(authorization: str | None = Header(default=None)) -> None:
        if settings.home_token and bearer(authorization) != settings.home_token:
            raise HTTPException(401, "invalid or missing home token")

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        if settings.admin_token and bearer(authorization) != settings.admin_token:
            raise HTTPException(401, "invalid or missing admin token")

    def known_home(patient_id: str) -> dict[str, Any]:
        summary = store.home_summary(patient_id)
        if summary is None or "consensus" not in summary:
            if patient_id not in store.home_ids():
                raise HTTPException(404, f"unknown patient {patient_id!r}")
            summary = service.recompute_home(store, settings, patient_id)
        return summary

    # ------------------------------------------------------------------ health
    @app.get("/healthz", response_model=Healthz)
    def healthz() -> Healthz:
        db = store.ping()
        return Healthz(status="ok" if db else "degraded", version=VERSION, schema_version=SCHEMA_VERSION, db=db,
                       llm=settings.llm, time=datetime.now(UTC))

    # ------------------------------------------------------------------ ingest
    @app.post("/v1/events", response_model=EventsResult)
    async def post_events(request: Request, authorization: str | None = Header(default=None)) -> EventsResult:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "body must be JSON {events: [...]}") from None
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list):
            raise HTTPException(400, "body must be JSON {events: [...]}")
        if len(events) > MAX_BATCH:
            raise HTTPException(413, f"max {MAX_BATCH} events per batch")
        # Pairing token: every source (hub, glasses, laptop browser apps) sends Authorization: Bearer <token>.
        # Browser apps get it from their pairing link (?t=...). Off when KAIKU_HOME_TOKEN is unset (local dev).
        if settings.home_token and bearer(authorization) != settings.home_token:
            raise HTTPException(401, "invalid or missing home token")

        ok: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for raw in events:
            rid = raw.get("id") if isinstance(raw, dict) else None
            try:
                env = validate(raw)
            except ContractError as e:
                rejected.append({"id": rid, "error": str(e)[:300]})
                continue
            if env.type not in UPLINKABLE:
                rejected.append({"id": str(env.id), "error": f"type {env.type!r} is not uplinkable (obs.* only)"})
                continue
            ok.append(env.model_dump(mode="json", exclude_none=True))
        inserted, dupes = store.insert_events(ok)
        if inserted:
            for home in sorted({e["home_id"] for e in ok}):
                service.recompute_home(store, settings, home)
        if any(e["type"] == "obs.safety_flag" for e in ok):
            log.warning("safety_flag_received", "priority event ingested",
                        homes=sorted({e["home_id"] for e in ok if e["type"] == "obs.safety_flag"}))
        return EventsResult(accepted=inserted, duplicates=dupes, rejected=rejected)

    @app.get("/v1/events", response_model=LiveEventsResponse)
    def get_events(home_id: str | None = None, since: str | None = None,
                   limit: int = Query(default=100, ge=1, le=1000)) -> LiveEventsResponse:
        """Most recent first."""
        return LiveEventsResponse(events=store.recent_events(home_id, norm_ts(since), limit))

    # ------------------------------------------------------------------ commands
    @app.get("/v1/commands", response_model=CommandsResponse, dependencies=[Depends(require_home_token)])
    def get_commands(home_id: str, since: str | None = None) -> CommandsResponse:
        service.maybe_queue_phq9_due(store, settings, home_id)
        return CommandsResponse(commands=store.pending_commands(home_id, norm_ts(since)))

    @app.websocket("/v1/stream/{home_id}")
    async def stream(ws: WebSocket, home_id: str, token: str | None = None) -> None:
        if settings.home_token and token != settings.home_token:
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            while True:
                for cmd in await asyncio.to_thread(store.pending_commands, home_id, None):
                    await ws.send_json(cmd)
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):
            return

    # ------------------------------------------------------------------ nudges
    @app.get("/v1/nudge", response_model=NudgeResponse)
    def get_nudge(home_id: str) -> NudgeResponse:
        return service.nudge(store, settings, home_id)

    @app.get("/v1/me", response_model=MeResponse)
    def get_me(home_id: str) -> MeResponse:
        """Person-facing view (plain language). Works for a home with no data yet."""
        row = store.home_summary(home_id) or (service.recompute_home(store, settings, home_id)
                                               if home_id in store.home_ids() else None)
        return service.me(store, settings, home_id, row)

    # ------------------------------------------------------------------ companion mind (plan 03 §3–§6)
    @app.post("/v1/companion/session", response_model=CompanionSessionResponse,
              dependencies=[Depends(require_home_token)])
    def companion_session(req: CompanionSessionRequest) -> CompanionSessionResponse:
        """Bootstrap one Gemini Live session as Kaiku: model, voice, system instruction, tools, context card and an
        ephemeral Live token (null without a cloud Gemini key)."""
        return mind.start_session(store, settings, req)

    @app.post("/v1/companion/tool", response_model=CompanionToolResult, dependencies=[Depends(require_home_token)])
    def companion_tool(call: CompanionToolCall) -> CompanionToolResult:
        """A device forwards a model's tool call; the cloud checks and executes it deterministically."""
        return mind.run_tool(store, settings, call)

    @app.post("/v1/companion/episode", response_model=EpisodeResult, dependencies=[Depends(require_home_token)])
    def companion_episode(ep: EpisodeIn) -> EpisodeResult:
        try:
            return EpisodeResult(ok=True, id=mind.record_episode(store, ep))
        except ValueError as e:  # includes MemoryRefused (thread topic)
            raise HTTPException(422, str(e)) from None

    # "What Kaiku remembers" — person-facing only; no clinician route reads memories.
    @app.get("/v1/me/memories", response_model=MemoriesResponse)
    def me_memories(home_id: str) -> MemoriesResponse:
        return MemoriesResponse(home_id=home_id, remember=mind_memory.remembering(store, home_id),
                                memories=mind_memory.listing(store, home_id))

    @app.delete("/v1/me/memories/{memory_id}", response_model=DeletedResponse)
    def me_forget_one(memory_id: int, home_id: str) -> DeletedResponse:
        n = store.memory_delete(home_id, memory_id)
        if not n:
            raise HTTPException(404, "no such memory")
        return DeletedResponse(deleted=n)

    @app.delete("/v1/me/memories", response_model=DeletedResponse)
    def me_forget_all(home_id: str) -> DeletedResponse:
        return DeletedResponse(deleted=store.memory_delete(home_id))

    @app.put("/v1/me/memory_settings", response_model=MemorySettings)
    def me_memory_settings(home_id: str, body: MemorySettings) -> MemorySettings:
        mind_memory.set_remembering(store, home_id, body.remember)
        return body

    # ------------------------------------------------------------------ voice (D27: one voice, keyed lines)
    @app.get("/v1/voice", response_model=VoiceLinesResponse)
    def get_voice_lines(lang: VoiceLang = "en") -> VoiceLinesResponse:
        """Every keyed line as text (captions, offline). Source: config/voice_lines.toml."""
        return VoiceLinesResponse(lang=lang, voice=voice.voice_name(), model=voice.tts_model(), lines=voice.lines(lang))

    @app.get("/v1/voice/{line_key}", response_class=Response,
             responses={200: {"content": {"audio/wav": {}}}, 404: {}, 503: {}})
    def get_voice(line_key: str, lang: VoiceLang = "en") -> Response:
        """Audio (wav) for one line in Kaiku's voice. Cached on disk; 503 + JSON hint if TTS is unavailable."""
        try:
            data = voice.audio(line_key, lang)
        except voice.UnknownLine:
            raise HTTPException(404, f"unknown line {line_key!r} (see GET /v1/voice)") from None
        except voice.VoiceUnavailable as e:
            log.warning("voice_unavailable", str(e), key=line_key, lang=lang)
            return JSONResponse(status_code=503, content={
                "detail": "voice audio unavailable", "reason": str(e),
                "hint": "show the text from GET /v1/voice instead; set GEMINI_API_KEY on the cloud or pre-render "
                        "with `make voice-prerender`"})
        return Response(content=data, media_type="audio/wav", headers={"cache-control": "public, max-age=86400"})

    # ------------------------------------------------------------------ clinician
    @app.get("/v1/patients", response_model=PatientsResponse)
    def patients() -> PatientsResponse:
        summaries = store.home_summaries()
        for h in store.home_ids():
            if h not in summaries or "summary" not in summaries[h]:
                summaries[h] = service.recompute_home(store, settings, h)
        return PatientsResponse(patients=service.ranked_summaries(list(summaries.values())),
                                rule_version=service.active_criteria(store).rule_version)

    @app.get("/v1/patients/{patient_id}/consensus", response_model=Consensus)
    def patient_consensus(patient_id: str) -> Consensus:
        return service.get_consensus(store, settings, known_home(patient_id), log)

    @app.get("/v1/patients/{patient_id}/phq9", response_model=Phq9History)
    def patient_phq9(patient_id: str) -> Phq9History:
        known_home(patient_id)
        return service.phq9_history(store, settings, patient_id)

    @app.get("/v1/patients/{patient_id}/timeline", response_model=TimelineResponse)
    def patient_timeline(patient_id: str, metrics: str | None = None,
                         days: int = Query(default=30, ge=7, le=120)) -> TimelineResponse:
        known_home(patient_id)
        wanted = [m.strip() for m in metrics.split(",") if m.strip()] if metrics else None
        return TimelineResponse(patient_id=patient_id,
                                series=service.timeline(store, patient_id, wanted, days))

    @app.post("/v1/patients/{patient_id}/actions", response_model=ActionResult)
    def patient_action(patient_id: str, req: ActionRequest) -> ActionResult:
        known_home(patient_id)
        store.log_action(patient_id, req.action, req.note, req.by)
        if req.action == "send_message":
            text = req.note or "Your care team would like to check in with you soon."
            cmd = make("cmd.hub", {"clinician_message": {"text": text}}, source="cloud", home_id=patient_id)
            store.queue_command(cmd.model_dump(mode="json", exclude_none=True))
        log.info("clinician_action", req.action, patient=patient_id)
        row = service.recompute_home(store, settings, patient_id)  # acknowledge can release needs_call / safety
        return ActionResult(ok=True, patient_id=patient_id, action=req.action, state=row["summary"]["state"])

    # ------------------------------------------------------------------ admin / eval
    @app.post("/v1/admin/recompute", dependencies=[Depends(require_admin)])
    def admin_recompute(eval: bool = False) -> dict[str, Any]:
        return nightly.run(store, settings, with_eval=eval, eval_runner=eval_runner)

    @app.post("/v1/admin/reset", dependencies=[Depends(require_admin)])
    def admin_reset() -> dict[str, Any]:
        """Demo reset: delete simulated data (live/real events stay). Re-seed with `make seed`."""
        deleted = store.delete_sim()
        service.recompute_all(store, settings)
        log.warning("demo_reset", f"deleted {deleted} simulated events")
        return {"deleted": deleted}

    # ------------------------------------------------------------------ criteria tuning (config/criteria.toml)
    @app.get("/v1/admin/criteria", response_model=CriteriaResponse, dependencies=[Depends(require_admin)])
    def get_criteria() -> CriteriaResponse:
        return service.criteria_response(store)

    @app.put("/v1/admin/criteria", response_model=CriteriaResponse, dependencies=[Depends(require_admin)])
    def put_criteria(update: CriteriaUpdate) -> CriteriaResponse:
        """Apply a live override (validated → 422 if invalid), recompute everyone. criteria=null resets to the file."""
        res = service.set_criteria(store, settings, update.criteria, update.by)
        log.warning("criteria_changed", res.rule_version, origin=res.origin, by=update.by)
        return res

    @app.post("/v1/admin/criteria/preview", response_model=CriteriaPreview, dependencies=[Depends(require_admin)])
    def preview_criteria(update: CriteriaUpdate, eval: bool = False) -> CriteriaPreview:
        """Dry run: who would change state (and optionally the simulation) under the candidate. Nothing saved."""
        return service.preview(store, update.criteria, with_eval=eval)

    @app.get("/v1/eval", response_model=EvalResult)
    def get_eval() -> EvalResult:
        cached = store.kv_get("eval")
        if cached and cached.get("rule_version") == service.active_criteria(store).rule_version:
            return EvalResult.model_validate(cached)
        crit = service.active_criteria(store)
        result = eval_runner(crit) if eval_runner else nightly.run_eval(n_patients=18, shards=2, criteria=crit)
        store.kv_set("eval", result.model_dump(mode="json"))
        return result

    # ------------------------------------------------------------------ node health (from hubs)
    @app.put("/v1/health/{home_id}", dependencies=[Depends(require_home_token)])
    def put_health(home_id: str, report: NodeHealthReport) -> dict[str, bool]:
        store.save_node_health(home_id, report.model_dump(mode="json"))
        return {"ok": True}

    @app.get("/v1/health", response_model=HealthOverview)
    def get_health() -> HealthOverview:
        return HealthOverview(homes=store.node_health())

    # ------------------------------------------------------------------ static web app (last!)
    web_dir = settings.web_dir
    if web_dir and Path(web_dir).is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    else:
        @app.get("/", include_in_schema=False)
        def root() -> JSONResponse:
            return JSONResponse({"service": "kaiku-cloud", "docs": "/docs", "web": "not built (make web-build)"})

    return app


def __getattr__(name: str) -> Any:
    """Lazy module-level `app` for `uvicorn kaiku_cloud.api.main:app` (importing the module stays side-effect free)."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
