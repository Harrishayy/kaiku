"""Kaiku cloud API (FastAPI). Local: `make cloud-local` (uvicorn kaiku_cloud.api.main:app). Modal: cloud/app.py.

Routes are listed in docs/plans/01-foundation.md §6.7 (ground truth for shapes: kaiku_contracts.api). The static web app (Next.js export) is mounted at `/` last,
so /v1/* and /healthz always win.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from kaiku_contracts import SCHEMA_VERSION, UPLINKABLE, ContractError, make, validate
from kaiku_contracts.api import (
    ActionRequest,
    ActionResult,
    APIDiscoveryResponse,
    ClinicianAskRequest,
    ClinicianAskResponse,
    ClinicianBrief,
    CommandAckResult,
    CommandsResponse,
    CompanionSessionRequest,
    CompanionSessionResponse,
    CompanionToolCall,
    CompanionToolResult,
    Consensus,
    ConstellationResponse,
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
    IntelligenceHealth,
    LiveEventsResponse,
    MemoriesResponse,
    MemorySettings,
    MeResponse,
    NodeHealthReport,
    NudgeResponse,
    PatientInsight,
    PatientsResponse,
    Phq9History,
    PostcardRequest,
    PostcardResponse,
    TaskObservationsResponse,
    TimelineResponse,
    Transcript,
    TranscriptsResponse,
    VoiceLang,
    VoiceLinesResponse,
    VoiceSayRequest,
)
from kaiku_contracts.jlog import get_logger

from .. import clinician_chat, service, voice
from .. import insight as patient_insight
from ..jobs import nightly
from ..llm import ledger
from ..mind import affect as mind_affect
from ..mind import brief as mind_brief
from ..mind import graph as mind_graph
from ..mind import memory as mind_memory
from ..mind import nightly as mind_nightly
from ..mind import postcard as mind_postcard
from ..mind import session as mind
from ..settings import TZ, VERSION, Settings
from ..store.db import Store
from .auth import Access

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
    ledger.bind(store)  # usage ledger rows (no content) from every model adapter
    app = FastAPI(title="Kaiku cloud", version=VERSION)
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    if after_write is not None:  # e.g. Modal Volume commit after mutating requests
        commit_lock = threading.Lock()

        def _commit() -> bool:
            with commit_lock:
                try:
                    after_write()
                    return True
                except Exception as e:
                    log.warning("after_write_failed", type(e).__name__)
                    return False

        @app.middleware("http")
        async def _after_write(request: Request, call_next):
            before = store.mutation_count()
            response = await call_next(request)
            changed = store.mutation_count() != before
            paid_voice_read = request.method == "GET" and request.url.path.startswith("/v1/voice/")
            if (request.method in ("POST", "PUT", "DELETE") or changed or paid_voice_read) and response.status_code < 400:
                if not await asyncio.to_thread(_commit):
                    return JSONResponse({"detail": "durable commit unavailable; data may have been saved"},
                                        status_code=503)
            return response

    access = Access(settings)

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        denial = await access.authorize(request)
        return denial if denial is not None else await call_next(request)

    def summary_is_current(row: dict[str, Any]) -> bool:
        try:
            computed = datetime.fromisoformat(row["consensus"]["computed_at"].replace("Z", "+00:00"))
            return (computed.astimezone(TZ).date() == service.today_local() and
                    row["consensus"]["rule_version"] == service.active_criteria(store).rule_version)
        except (KeyError, ValueError, TypeError):
            return False

    def known_home(patient_id: str) -> dict[str, Any]:
        summary = store.home_summary(patient_id)
        if summary is None or "consensus" not in summary or not summary_is_current(summary):
            if patient_id not in store.home_ids():
                raise HTTPException(404, f"unknown patient {patient_id!r}")
            summary = service.recompute_home(store, settings, patient_id)
        return summary

    # ------------------------------------------------------------------ health
    @app.get("/v1/discovery", response_model=APIDiscoveryResponse)
    def discovery() -> APIDiscoveryResponse:
        # Public protocol identity only. Discovery never enrolls a home or supplies credentials.
        configured = bool(access.homes or access.admin or access.clinician)
        mode = "demo" if access.demo else "authenticated" if configured else "unconfigured"
        return APIDiscoveryResponse(mode=mode, auth_required=not access.demo,
                                    capabilities=["companion_voice", "observations", "monitoring"])

    @app.get("/healthz", response_model=Healthz)
    def healthz(response: Response) -> Healthz:
        db = store.ping()
        criteria_ready = True
        try:
            service.active_criteria(store)
        except Exception as e:
            criteria_ready = False
            log.warning("readiness_criteria_invalid", type(e).__name__)
        ready = db and criteria_ready
        if not ready:
            response.status_code = 503
        return Healthz(status="ok" if ready else "degraded", version=VERSION, schema_version=SCHEMA_VERSION, db=db,
                       llm=settings.llm, time=datetime.now(UTC))

    # ------------------------------------------------------------------ ingest
    @app.post("/v1/events", response_model=EventsResult)
    async def post_events(request: Request) -> EventsResult:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "body must be JSON {events: [...]}") from None
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list):
            raise HTTPException(400, "body must be JSON {events: [...]}")
        if len(events) > MAX_BATCH:
            raise HTTPException(413, f"max {MAX_BATCH} events per batch")
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
    @app.get("/v1/commands", response_model=CommandsResponse)
    def get_commands(home_id: str, since: str | None = None) -> CommandsResponse:
        service.maybe_queue_phq9_due(store, settings, home_id)
        return CommandsResponse(commands=store.pending_commands(home_id, norm_ts(since)))

    @app.post("/v1/commands/{command_id}/ack", response_model=CommandAckResult)
    def acknowledge_command(command_id: str, home_id: str) -> CommandAckResult:
        if not store.acknowledge_command(home_id, command_id):
            raise HTTPException(404, "no such command")
        return CommandAckResult(ok=True, id=command_id)

    @app.websocket("/v1/stream/{home_id}")
    async def stream(ws: WebSocket, home_id: str, token: str | None = None) -> None:
        if not access.home_allowed(token, home_id):
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
        row = known_home(home_id) if home_id in store.home_ids() else None
        return service.me(store, settings, home_id, row)

    # ------------------------------------------------------------------ companion mind (plan 03 §3–§6)
    @app.post("/v1/companion/session", response_model=CompanionSessionResponse)
    def companion_session(req: CompanionSessionRequest) -> CompanionSessionResponse:
        """Bootstrap one Gemini Live session as Kaiku: model, voice, system instruction, tools, context card and an
        ephemeral Live token (null without a cloud Gemini key)."""
        try:
            return mind.start_session(store, settings, req)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.post("/v1/companion/tool", response_model=CompanionToolResult)
    def companion_tool(call: CompanionToolCall) -> CompanionToolResult:
        """A device forwards a model's tool call; the cloud checks and executes it deterministically."""
        return mind.run_tool(store, settings, call)

    @app.post("/v1/companion/episode", response_model=EpisodeResult)
    def companion_episode(ep: EpisodeIn, background: BackgroundTasks) -> EpisodeResult:
        try:
            eid = mind.record_episode(store, ep)
            kept = store.transcript_exists(ep.home_id, eid)
            if kept:  # after the response: one Gemma call relabels this reflection's level, tone and themes
                background.add_task(mind_affect.label_episode, store, ep.home_id, eid)
            return EpisodeResult(ok=True, id=eid, transcript_stored=kept)
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
        mind_graph.rebuild(store, home_id)  # its graph node + vector go with it
        return DeletedResponse(deleted=n)

    @app.delete("/v1/me/memories", response_model=DeletedResponse)
    def me_forget_all(home_id: str) -> DeletedResponse:
        n = store.memory_delete(home_id)
        mind_graph.rebuild(store, home_id)
        mind_affect.forget_heard(store, home_id)  # "forget everything" covers what the companion noted about tone
        return DeletedResponse(deleted=n)

    # Opt-in conversation transcripts — person-facing only; no clinician route reads them (tested).
    @app.get("/v1/me/transcripts", response_model=TranscriptsResponse)
    def me_transcripts(home_id: str) -> TranscriptsResponse:
        return TranscriptsResponse(home_id=home_id, transcripts=[
            Transcript(episode_id=t["episode_id"], surface=t["surface"], intent=t["intent"], start=t["start"],
                       turns=t["turns"]) for t in store.transcripts(home_id)])

    @app.delete("/v1/me/transcripts/{episode_id}", response_model=DeletedResponse)
    def me_transcript_delete(episode_id: str, home_id: str) -> DeletedResponse:
        n = store.transcript_delete(home_id, episode_id)
        if not n:
            raise HTTPException(404, "no such transcript")
        mind_affect.forget(store, home_id, episode_id)  # the summary derived from those words goes with them
        return DeletedResponse(deleted=n)

    @app.delete("/v1/me/transcripts", response_model=DeletedResponse)
    def me_transcripts_delete_all(home_id: str) -> DeletedResponse:
        mind_affect.forget(store, home_id)
        store.kv_delete(f"feel:{home_id}")
        return DeletedResponse(deleted=store.transcript_delete(home_id))

    @app.get("/v1/me/constellation", response_model=ConstellationResponse)
    def me_constellation(home_id: str) -> ConstellationResponse:
        """"Your constellation": people, places, activities and what helps — no health data, scores or states."""
        return ConstellationResponse.model_validate(mind_graph.constellation(store, home_id))

    @app.post("/v1/companion/postcard", response_model=PostcardResponse,
              responses={503: {}})
    def companion_postcard(req: PostcardRequest) -> Any:
        """Walk postcard from stats only (Nano Banana 2 Lite). 503 + hint when unavailable: show the static card."""
        try:
            pid, cached, model = mind_postcard.make(store, req, mind._gate().check)
        except mind_postcard.PostcardUnavailable as e:
            return JSONResponse(status_code=503, content={
                "detail": "postcard unavailable", "reason": str(e),
                "hint": "show the app's own static walk card; postcards need GEMINI_API_KEY on the cloud"})
        return PostcardResponse(id=pid, url=f"/v1/me/postcards/{pid}", cached=cached, model=model)

    @app.get("/v1/me/postcards/{postcard_id}", response_class=Response,
             responses={200: {"content": {"image/png": {}}}, 404: {}})
    def me_postcard(postcard_id: str) -> Response:
        got = mind_postcard.load(store, postcard_id)
        if not got:
            raise HTTPException(404, "no such postcard")
        return Response(content=got[0], media_type=got[1], headers={"cache-control": "public, max-age=604800"})

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

    @app.post("/v1/voice/say", response_class=Response,
              responses={200: {"content": {"audio/wav": {}}}, 422: {}, 503: {}})
    def post_voice_say(req: VoiceSayRequest) -> Response:
        """A dynamic line (not keyed) in Kaiku's one voice: audio/wav, cached by text hash. 503 + hint without TTS."""
        if mind._gate().check(req.text):
            raise HTTPException(422, "crisis text is shown verbatim, never voiced here")
        try:
            data = voice.say(req.text, req.lang)
        except voice.VoiceUnavailable as e:
            log.warning("voice_unavailable", str(e), key="say", lang=req.lang)
            return JSONResponse(status_code=503, content={
                "detail": "voice audio unavailable", "reason": str(e),
                "hint": "show the text and let the person retry when Kaiku’s voice is available"})
        return Response(content=data, media_type="audio/wav", headers={"cache-control": "private, max-age=86400"})

    # ------------------------------------------------------------------ clinician
    @app.get("/v1/patients", response_model=PatientsResponse)
    def patients() -> PatientsResponse:
        summaries = store.home_summaries()
        for h in store.home_ids():
            if h not in summaries or "summary" not in summaries[h] or not summary_is_current(summaries[h]):
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

    @app.get("/v1/patients/{patient_id}/tasks", response_model=TaskObservationsResponse)
    def patient_tasks(patient_id: str, days: int = Query(default=7, ge=1, le=30)) -> TaskObservationsResponse:
        known_home(patient_id)
        now = datetime.now(UTC)
        observations = store.task_observations(patient_id, norm_ts((now - timedelta(days=days)).isoformat()),
                                               norm_ts(now.isoformat()))
        return TaskObservationsResponse(patient_id=patient_id, observations=observations, computed_at=now)

    @app.post("/v1/patients/{patient_id}/ask", response_model=ClinicianAskResponse)
    def patient_ask(patient_id: str, req: ClinicianAskRequest) -> ClinicianAskResponse:
        return clinician_chat.ask(store, settings, patient_id, req.question, known_home(patient_id))

    @app.get("/v1/patients/{patient_id}/insight", response_model=PatientInsight)
    def patient_insight_route(patient_id: str, generate: bool = True) -> PatientInsight:
        """Gemma's evidence-cited review, the steps that produced it, week comparison, learned routine, permitted
        graph and data coverage. `generate=false` never calls a model (cached review or deterministic template)."""
        return patient_insight.insight(store, settings, patient_id, known_home(patient_id), generate=generate)

    @app.get("/v1/patients/{patient_id}/brief", response_model=ClinicianBrief)
    def patient_brief(patient_id: str) -> ClinicianBrief:
        """This week's brief (POST /v1/admin/weekly); the deterministic template until one is generated."""
        row = known_home(patient_id)
        c = Consensus.model_validate(row["consensus"])
        return mind_brief.current(store.kv_get(mind_brief.key(patient_id)), c) or \
            mind_brief.generate(store, patient_id, c, use_model=False)

    @app.post("/v1/patients/{patient_id}/actions", response_model=ActionResult)
    def patient_action(patient_id: str, req: ActionRequest) -> ActionResult:
        known_home(patient_id)
        when = None
        if req.ts is not None:
            at = req.ts if req.ts.tzinfo else req.ts.replace(tzinfo=UTC)
            if at > datetime.now(UTC) + timedelta(minutes=1):
                raise HTTPException(422, "an action cannot be logged in the future")
            when = norm_ts(at.isoformat())
        store.log_action(patient_id, req.action, req.note, req.by, when)
        if req.action == "send_message":
            text = req.note or "Your care team would like to check in with you soon."
            cmd = make("cmd.hub", {"clinician_message": {"text": text}}, source="cloud", home_id=patient_id)
            store.queue_command(cmd.model_dump(mode="json", exclude_none=True))
        log.info("clinician_action", req.action, patient=patient_id)
        row = service.recompute_home(store, settings, patient_id)  # acknowledge can release needs_call / safety
        return ActionResult(ok=True, patient_id=patient_id, action=req.action, state=row["summary"]["state"])

    # ------------------------------------------------------------------ admin / eval
    @app.post("/v1/admin/recompute")
    def admin_recompute(eval: bool = False) -> dict[str, Any]:
        return nightly.run(store, settings, with_eval=eval, eval_runner=eval_runner)

    @app.post("/v1/admin/reflect")
    def admin_reflect(home_id: str | None = None) -> dict[str, Any]:
        """Daily reflection with the flagship model (rule fallback without a key). Nightly job + on demand.
        Clears today's cached plan first so a re-run uses the model."""
        from ..mind import reflect
        from ..mind.card import build_card

        out = {}
        now = datetime.now(UTC)
        for hid in ([home_id] if home_id else store.home_ids()):
            store.kv_delete(f"reflect:{hid}:{now.astimezone(reflect.TZ).date().isoformat()}")
            card = build_card(store, settings, hid, intent="talk", now=now).model_dump(mode="json")
            store.kv_delete(f"reflect:{hid}:{now.astimezone(reflect.TZ).date().isoformat()}")
            out[hid] = reflect.plan(store, hid, card, now=now, use_model=True, log=log)
        return {"reflected": len(out), "plans": out}

    @app.post("/v1/admin/nightly-mind")
    def admin_nightly_mind(home_id: str | None = None) -> dict[str, Any]:
        """Graph rebuild + Embedding 2 backfill + validated consolidation diffs + pre-render list (plan 06 §2)."""
        homes = [home_id] if home_id else sorted({*store.home_ids(), *store.memory_homes()})
        return mind_nightly.run(store, homes)

    @app.post("/v1/admin/weekly")
    def admin_weekly(home_id: str | None = None) -> dict[str, Any]:
        """Weekly clinician briefs (flagship, grounded in metric ids; template fallback), stored per patient."""
        out = {}
        for hid in ([home_id] if home_id else store.home_ids()):
            b = mind_brief.generate(store, hid, Consensus.model_validate(known_home(hid)["consensus"]))
            store.kv_set(mind_brief.key(hid), b.model_dump(mode="json"))
            out[hid] = {"by": b.by, "sections": len(b.sections)}
        return {"briefs": out}

    @app.post("/v1/admin/reset")
    def admin_reset(home_id: str | None = None) -> dict[str, Any]:
        """Demo reset: delete simulated data (live/real events stay). `home_id` limits it to one person, so
        re-seeding them leaves everyone else as they were."""
        deleted = store.delete_sim(home_id)
        service.recompute_all(store, settings)
        log.warning("demo_reset", f"deleted {deleted} simulated events", home=home_id or "all")
        return {"deleted": deleted, "home_id": home_id}

    # ------------------------------------------------------------------ criteria tuning (config/criteria.toml)
    @app.get("/v1/admin/criteria", response_model=CriteriaResponse)
    def get_criteria() -> CriteriaResponse:
        return service.criteria_response(store)

    @app.put("/v1/admin/criteria", response_model=CriteriaResponse)
    def put_criteria(update: CriteriaUpdate) -> CriteriaResponse:
        """Apply a live override (validated → 422 if invalid), recompute everyone. criteria=null resets to the file."""
        res = service.set_criteria(store, settings, update.criteria, update.by)
        log.warning("criteria_changed", res.rule_version, origin=res.origin, by=update.by)
        return res

    @app.post("/v1/admin/criteria/preview", response_model=CriteriaPreview)
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
    @app.put("/v1/health/{home_id}")
    def put_health(home_id: str, report: NodeHealthReport) -> dict[str, bool]:
        store.save_node_health(home_id, report.model_dump(mode="json"))
        return {"ok": True}

    @app.get("/v1/health/intelligence", response_model=IntelligenceHealth)
    def get_intelligence(days: int = Query(default=7, ge=1, le=90)) -> IntelligenceHealth:
        """Usage ledger: which models ran, how often, how fast, how often we fell back (no content)."""
        return IntelligenceHealth.model_validate(ledger.summary(store, days, TZ))

    @app.get("/v1/health", response_model=HealthOverview)
    def get_health() -> HealthOverview:
        return HealthOverview(homes=store.node_health())

    # ------------------------------------------------------------------ dashboard: the week + graph (D34)
    from . import dashboard

    dashboard.register(app, store, settings, known_home)

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
