"""Real end-to-end check of Kaiku's intelligence with real (cheap) model calls — `make e2e-intelligence`.

Starts a throwaway cloud (free port, temp DB, temp voice cache) with the repo `.env` (or KAIKU_ENV_FILE), seeds the
demo cohort, then exercises what the iPhone/Mac apps do:

  1. POST /v1/companion/session (iphone)   -> live_token minted (model locked), live_setup returned
  2. Gemini Live with ONLY that token       -> typed turn: audio (Sulafat) + output transcript back
                                               spoken turn (macOS `say` -> 16 kHz PCM, automatic VAD ends it):
                                               input transcript + audio back; tool calls forwarded to the cloud
                                               barge-in: speaking over Kaiku -> serverContent.interrupted
  3. GET /v1/voice/{key} + POST /v1/voice/say -> Gemini TTS wav in the same voice
  4. ask_mind through /v1/companion/tool    -> answer from the mind router (Gemini)
  5. knowledge graph: nightly-mind rebuild + GET /v1/me/constellation non-empty

Costs a few cents (budget ledger + hard cap apply). Exit 0 = everything required passed. Without a key/ADC the
script says what is missing and exits 2; the offline unit tests (`make test`) never make these calls.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WS = ("wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService."
      "BidiGenerateContentConstrained?access_token=")
HOME = "demo-aino"
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)
    if not ok:
        fails.append(name)
    return ok


def note(name: str, detail: str) -> None:
    print(f"info {name}  ({detail})", flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def speech_pcm(text: str, tmp: Path) -> bytes | None:
    """16 kHz mono PCM16 of `text` from macOS `say` (test input only), or None where `say` doesn't exist."""
    if not shutil.which("say"):
        return None
    out = tmp / "speech.wav"
    subprocess.run(["say", "-o", str(out), "--data-format=LEI16@16000", text], check=True)
    with wave.open(str(out)) as w:
        return w.readframes(w.getnframes())


async def live_turns(base: str, s: dict, speech: bytes | None, barge: bytes | None) -> None:
    import websockets

    tok = s["live_token"]["token"]
    t0 = time.time()
    async with websockets.connect(WS + tok, max_size=None) as ws:
        await ws.send(json.dumps({"setup": s["live_setup"]}))
        tools_seen: list[str] = []

        async def turn(send, label: str, barge_in: bytes | None = None, timeout: float = 40) -> dict:
            """Send one turn, collect until turnComplete. With `barge_in`: once Kaiku is talking, stream it."""
            await send()
            got = {"audio": 0, "out": "", "in": "", "interrupted": False}
            barged = False
            end = time.time() + timeout
            while time.time() < end:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.time()))
                except TimeoutError:
                    break
                m = json.loads(raw)
                if "toolCall" in m:
                    for c in m["toolCall"].get("functionCalls", []):
                        tools_seen.append(c["name"])
                        r = httpx.post(f"{base}/v1/companion/tool", json={
                            "home_id": HOME, "surface": "iphone", "session_id": s["session_id"],
                            "name": c["name"], "args": c.get("args") or {}}, timeout=60).json()
                        await ws.send(json.dumps({"toolResponse": {"functionResponses": [{
                            "id": c.get("id"), "name": c["name"], "response": {"result": r.get("result") or r}}]}}))
                sc = m.get("serverContent") or {}
                for p in (sc.get("modelTurn") or {}).get("parts") or []:
                    if "inlineData" in p:
                        got["audio"] += len(base64.b64decode(p["inlineData"]["data"]))
                got["out"] += (sc.get("outputTranscription") or {}).get("text", "")
                got["in"] += (sc.get("inputTranscription") or {}).get("text", "")
                if barge_in is not None and not barged and got["audio"] > 48_000:  # ~1 s of Kaiku talking
                    barged = True
                    await stream(barge_in)
                if sc.get("interrupted"):
                    got["interrupted"] = True
                    if barge_in is not None:
                        break
                if sc.get("turnComplete") and (barge_in is None or barged):
                    break
            note(label, f"{got['audio'] / 48000:.1f}s audio, out={got['out'][:90]!r} in={got['in'][:60]!r}")
            return got

        async def stream(pcm: bytes) -> None:
            chunk = 3200  # 100 ms at 16 kHz PCM16, sent in real time like the phone
            silence = b"\0" * chunk
            for i in range(0, len(pcm), chunk):
                await ws.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(pcm[i:i + chunk]).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
                await asyncio.sleep(0.1)
            for _ in range(15):  # 1.5 s of quiet: automatic VAD ends the turn
                await ws.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(silence).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
                await asyncio.sleep(0.1)

        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        check("live: setupComplete with only the ephemeral token", "setupComplete" in first,
              f"{time.time() - t0:.1f}s")
        typed = await turn(lambda: ws.send(json.dumps({"realtimeInput": {"text": "Hi Kaiku, it's Aino. How are you?"}})),
                           "live typed turn")
        check("live: typed turn -> Kaiku audio + transcript", typed["audio"] > 24_000 and bool(typed["out"].strip()))
        if speech is None:
            note("live spoken turn", "skipped: no macOS `say` to make test speech")
            return
        spoken = await turn(lambda: stream(speech), "live spoken turn (automatic VAD)")
        check("live: spoken turn -> input transcript (VAD ended the turn)", bool(spoken["in"].strip()))
        check("live: spoken turn -> Kaiku answers in audio", spoken["audio"] > 24_000)
        if tools_seen:
            note("live tool calls", ", ".join(tools_seen))
        if barge is not None:
            story = await turn(lambda: ws.send(json.dumps({"realtimeInput": {
                "text": "Tell me a long, slow story about the lake in autumn, at least a minute long."}})),
                "live barge-in", barge_in=barge, timeout=60)
            check("live: speaking over Kaiku interrupts it (barge-in)", story["interrupted"])


def main() -> int:
    from kaiku_contracts.config import load_dotenv

    env_file = os.environ.get("KAIKU_ENV_FILE") or str(ROOT / ".env")
    load_dotenv(env_file)
    if not os.environ.get("GEMINI_API_KEY"):
        print(f"no GEMINI_API_KEY (looked in {env_file}): the apps' Live path needs it for ephemeral tokens. "
              "Paste a Gemini API key into .env as GEMINI_API_KEY=... (or set KAIKU_ENV_FILE).")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="kaiku-e2e-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "KAIKU_DB_PATH": str(tmp / "e2e.sqlite"), "KAIKU_VOICE_CACHE": str(tmp / "voice"),
           "KAIKU_CLOUD_URL": base, "KAIKU_NO_DOTENV": "1"}
    for k in ("KAIKU_HOME_TOKEN", "KAIKU_ADMIN_TOKEN"):
        env.pop(k, None)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "kaiku_cloud.api.main:app", "--port", str(port),
                             "--log-level", "warning"], cwd=ROOT, env=env, stdout=open(tmp / "cloud.log", "w"),
                            stderr=subprocess.STDOUT)
    try:
        for _ in range(80):
            try:
                if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        check("cloud up on a temp DB", httpx.get(f"{base}/healthz", timeout=5).status_code == 200, base)
        seeded = subprocess.run([sys.executable, "-m", "sim.seed_demo", "--url", base], cwd=ROOT, env=env,
                                capture_output=True, text=True)
        check("seeded demo cohort + Aino's memories/episodes", seeded.returncode == 0, seeded.stdout.strip()[-80:])
        c = httpx.Client(base_url=base, timeout=90)

        # 1. session bootstrap
        s = c.post("/v1/companion/session", json={"home_id": HOME, "surface": "iphone", "intent": "talk"}).json()
        check("session: live_token minted", bool(s.get("live_token")), f"model={s.get('model')} voice={s.get('voice')}")
        ls = s.get("live_setup") or {}
        vad = (ls.get("realtimeInputConfig") or {}).get("automaticActivityDetection") or {}
        check("session: live_setup carries persona + voice + automatic VAD",
              ls.get("model", "").endswith(s.get("model", "?")) and vad.get("disabled") is False
              and "Kaiku" in json.dumps(ls.get("systemInstruction")), f"vad={vad}")

        # 2. Live round trips with the token only
        if s.get("live_token"):
            speech = speech_pcm("Hi Kaiku. I went for a walk by the lake this morning and the air was lovely.", tmp)
            barge = speech_pcm("Kaiku, wait, sorry to interrupt, can I tell you something?", tmp)
            try:
                asyncio.run(live_turns(base, s, speech, barge))
            except Exception as e:
                check("live session", False, f"{type(e).__name__}: {str(e)[:200]}")

        # 3. TTS in the one voice
        r = c.get("/v1/voice/greet.morning", params={"lang": "en"})
        check("voice: keyed line -> Gemini TTS wav", r.status_code == 200 and r.content[:4] == b"RIFF",
              f"{r.status_code} {len(r.content)} bytes")
        r = c.post("/v1/voice/say", json={"text": "I'm back. Shall we carry on?", "lang": "en"})
        check("voice: dynamic line -> Gemini TTS wav", r.status_code == 200 and r.content[:4] == b"RIFF",
              f"{r.status_code} {len(r.content)} bytes")
        t = time.time()
        r2 = c.post("/v1/voice/say", json={"text": "I'm back. Shall we carry on?", "lang": "en"})
        check("voice: dynamic line cached", r2.content == r.content and time.time() - t < 1.0)

        # 4. ask_mind
        r = c.post("/v1/companion/tool", json={"home_id": HOME, "surface": "iphone", "session_id": s.get("session_id"),
                                               "name": "ask_mind", "args": {"question": "What is my sister called?",
                                                                            "kind": "memory"}}).json()
        res = r.get("result") or {}
        check("ask_mind answers from memory", r.get("ok") is True and "maija" in json.dumps(res).lower(),
              json.dumps(res)[:160])

        # 5. knowledge graph
        nm = c.post("/v1/admin/nightly-mind", params={"home_id": HOME}).json()
        note("nightly-mind", json.dumps(nm)[:200])
        g = c.get("/v1/me/constellation", params={"home_id": HOME}).json()
        labels = [n["label"] for n in g.get("nodes", [])]
        check("constellation non-empty after seeding", len(labels) > 0, f"{len(labels)} nodes, {len(g.get('edges', []))}"
              f" edges: {labels[:6]}")
        u = c.get("/v1/health/intelligence").json()
        note("usage ledger", json.dumps(u)[:300])
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        if fails:
            print(f"cloud log: {tmp / 'cloud.log'}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
