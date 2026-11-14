"""Environment + live system health report. Run `make doctor` first when anything is off.

Prints ✅ / ⚠️ / ❌ with a fix hint per line. Never prints secret values. Exit 1 if any ❌.
    python tools/doctor.py [--offline] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kaiku_contracts import ContractError, validate  # noqa: E402
from kaiku_contracts.config import load_dotenv  # noqa: E402

OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
ENV_KEYS_REQUIRED = ["KAIKU_HOME_ID", "MQTT_HOST", "MQTT_PORT", "KAIKU_CLOUD_URL"]
ENV_KEYS_OPTIONAL = ["GEMINI_API_KEY", "KAIKU_HOME_TOKEN", "HF_TOKEN", "MQTT_USER", "MQTT_PASS"]


@dataclass
class Check:
    section: str
    name: str
    status: str
    detail: str = ""
    fix: str = ""


def _version(cmd: list[str]) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else ""
    except (OSError, subprocess.TimeoutExpired):
        return None


def _num(v: str | None) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)", v or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def check_tools() -> list[Check]:
    out = []
    py = sys.version_info
    out.append(Check("tools", "python", OK if py >= (3, 11) else FAIL, f"{py.major}.{py.minor}.{py.micro}",
                     "run via `uv run` (uses .python-version 3.12)"))
    specs = [
        ("uv", ["uv", "--version"], None, "curl -LsSf https://astral.sh/uv/install.sh | sh"),
        ("git", ["git", "--version"], None, "install git"),
        ("node", ["node", "-v"], (20, 0), "install Node >= 20 (nvm)"),
        ("pnpm", ["pnpm", "-v"], None, "corepack enable  (or brew install pnpm)"),
        ("modal", ["modal", "--version"], None, "uv tool install modal  (cloud role only)"),
    ]
    for name, cmd, minv, fix in specs:
        v = _version(cmd)
        if v is None:
            out.append(Check("tools", name, WARN if name in ("modal", "pnpm") else FAIL, "not found", fix))
        elif minv and _num(v) < minv:
            out.append(Check("tools", name, FAIL, v, fix))
        else:
            out.append(Check("tools", name, OK, v))
    mosq = shutil.which("mosquitto") or next((p for p in ("/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto",
                                                         "/usr/sbin/mosquitto") if Path(p).exists()), None)
    out.append(Check("tools", "mosquitto", OK if mosq else FAIL, mosq or "not found",
                     "brew install mosquitto  |  sudo apt install mosquitto mosquitto-clients"))
    return out


def check_repo() -> list[Check]:
    out = []
    env = ROOT / ".env"
    if not env.exists():
        out.append(Check("config", ".env", WARN, "missing — using defaults", "make env"))
    else:
        out.append(Check("config", ".env", OK, "present"))
    missing = [k for k in ENV_KEYS_REQUIRED if not os.environ.get(k)]
    out.append(Check("config", "required env", WARN if missing else OK,
                     f"unset: {', '.join(missing)}" if missing else "all set", "fill .env (see .env.example)"))
    unset_opt = [k for k in ENV_KEYS_OPTIONAL if not os.environ.get(k)]
    out.append(Check("config", "optional env", OK, f"unset: {', '.join(unset_opt) or 'none'} (names only)"))
    r = subprocess.run([sys.executable, "-m", "kaiku_contracts.export", "--check"], capture_output=True, text=True)
    out.append(Check("contracts", "schemas current", OK if r.returncode == 0 else FAIL,
                     (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else "", "make contracts"))
    mcp = ROOT / ".mcp.json"
    servers = set(json.loads(mcp.read_text()).get("mcpServers", {})) if mcp.exists() else set()
    want = {"geminiDocs", "wearables"}
    out.append(Check("agents", ".mcp.json", OK if want <= servers else WARN, ", ".join(sorted(servers)) or "missing",
                     "restore .mcp.json from git; restart your agent to load MCP servers"))
    web = ROOT / "apps/web"
    if (web / "package.json").exists():
        out.append(Check("web", "node_modules", OK if (web / "node_modules").exists() else WARN,
                         "", "cd apps/web && pnpm install"))
    return out


def check_broker() -> tuple[list[Check], bool]:
    host, port = os.environ.get("MQTT_HOST", "localhost"), int(os.environ.get("MQTT_PORT", 1883))
    try:
        socket.create_connection((host, port), timeout=1.5).close()
        return [Check("live", "broker", OK, f"{host}:{port}")], True
    except OSError as e:
        return [Check("live", "broker", FAIL, f"{host}:{port} {e.strerror or e}", "make broker")], False


async def _heartbeats(wait_s: float = 1.5) -> dict[str, dict]:
    import aiomqtt

    from tools.busio import mqtt_kwargs

    seen: dict[str, dict] = {}
    async with aiomqtt.Client(**mqtt_kwargs()) as client:
        await client.subscribe("kaiku/v1/+/health/#")

        async def collect() -> None:
            async for m in client.messages:
                try:
                    env = validate(m.payload)
                except ContractError:
                    seen[str(m.topic)] = {"status": "invalid"}
                    continue
                age = (datetime.now(UTC) - env.ts).total_seconds()
                seen[str(m.topic)] = {"status": env.payload.status, "age_s": age, "sim": env.sim,
                                      "last_error": env.payload.last_error}

        try:
            await asyncio.wait_for(collect(), timeout=wait_s)
        except TimeoutError:
            pass
    return seen


def check_nodes() -> list[Check]:
    try:
        seen = asyncio.run(_heartbeats())
    except Exception as e:
        return [Check("live", "heartbeats", WARN, str(e))]
    if not seen:
        return [Check("live", "heartbeats", WARN, "no nodes have ever reported", "make sim  /  make hub")]
    out = []
    for topic, h in sorted(seen.items()):
        name = f"{topic.split('/')[2]}:{topic.split('/')[-1]}"
        age = h.get("age_s")
        if h["status"] == "invalid":
            out.append(Check("live", name, FAIL, "heartbeat violates contract", "check that node's version"))
        elif h["status"] == "down" or (age is not None and age > 15):
            out.append(Check("live", name, FAIL, f"{h['status']}, last seen {age:.0f}s ago" if age else h["status"],
                             "node offline — restart it; see §9.2"))
        else:
            tag = " (sim)" if h.get("sim") else ""
            st = OK if h["status"] == "ok" else WARN
            out.append(Check("live", name, st, f"{h['status']}{tag}, {age:.1f}s ago"
                             + (f", last_error={h['last_error']}" if h.get("last_error") else "")))
    return out


def check_cloud() -> list[Check]:
    import httpx

    url = os.environ.get("KAIKU_CLOUD_URL", "").rstrip("/")
    if not url:
        return [Check("cloud", "/healthz", WARN, "KAIKU_CLOUD_URL unset", "make cloud-local or set the Modal URL")]
    try:
        r = httpx.get(f"{url}/healthz", timeout=4)
        data = r.json()
        st = OK if r.status_code == 200 and data.get("status") == "ok" else WARN
        return [Check("cloud", "/healthz", st, f"{url} -> {data.get('status')} llm={data.get('llm')}")]
    except Exception as e:
        return [Check("cloud", "/healthz", FAIL, f"{url}: {type(e).__name__}", "make cloud-local / check Modal logs")]


def check_sources() -> list[Check]:
    """Last data time per consensus source (robot / glasses / laptop) for this home."""
    import httpx

    url = os.environ.get("KAIKU_CLOUD_URL", "").rstrip("/")
    home = os.environ.get("KAIKU_HOME_ID", "demo-aino")
    if not url:
        return []
    try:
        r = httpx.get(f"{url}/v1/patients", timeout=4)
        r.raise_for_status()
        me = next((p for p in r.json().get("patients", []) if p.get("id") == home), None)
    except Exception as e:
        return [Check("sources", "per-source data", WARN, f"{type(e).__name__}", "is the cloud up? make cloud-local")]
    if me is None:
        return [Check("sources", home, WARN, "home not known to the cloud yet", "make seed  /  run the hub")]
    out = []
    now = datetime.now(UTC)
    for b in me.get("sources", []):
        last = b.get("last_data_at")
        age_h = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 3600 if last else None
        verdict = b.get("verdict")
        st = WARN if verdict == "insufficient" or age_h is None or age_h > 48 else OK
        when = f"{age_h:.1f} h ago" if age_h is not None else "never"
        out.append(Check("sources", b.get("source", "?"), st, f"{verdict}, conf {b.get('confidence', 0):.2f}, last data {when}",
                         "that source isn't reporting — check its app/sim/uplink"))
    out.append(Check("sources", "consensus", OK, f"{me.get('state')} ({me.get('agreement')})"))
    return out


def check_gemini() -> list[Check]:
    import httpx

    key = os.environ.get("GEMINI_API_KEY")
    if not key and os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return check_platform()
    if not key:
        return [Check("cloud", "gemini key", WARN, "no GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT",
                      "set one in .env (ADC: gcloud auth application-default login)")]
    try:
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                      headers={"x-goog-api-key": key}, timeout=5)
        out = [Check("cloud", "gemini key", OK if r.status_code == 200 else FAIL, f"HTTP {r.status_code}",
                     "" if r.status_code == 200 else "check the key in AI Studio")]
    except Exception as e:
        return [Check("cloud", "gemini key", WARN, f"unreachable: {type(e).__name__}")]
    if out[0].status != OK:
        return out
    # Every configured model ID must exist for this key (metadata lookups only: free, no generation).
    from kaiku_contracts.config import get

    for role in ("gemini_live", "gemini_flagship", "gemini_fast", "tts", "lyria_realtime", "gemma_hosted"):
        mid = str(get("models", role, "") or "")
        if not mid or mid.startswith("VERIFY"):
            out.append(Check("cloud", f"model {role}", WARN, mid or "unset", "set it in config/kaiku.toml [models]"))
            continue
        try:
            r = httpx.get(f"https://generativelanguage.googleapis.com/v1beta/models/{mid}",
                          headers={"x-goog-api-key": key}, timeout=5)
            out.append(Check("cloud", f"model {role}", OK if r.status_code == 200 else WARN, f"{mid}: HTTP {r.status_code}",
                             "" if r.status_code == 200 else "ID not visible to this key — check the Gemini docs"))
        except Exception as e:
            out.append(Check("cloud", f"model {role}", WARN, f"{mid}: {type(e).__name__}"))
    return out


def check_platform() -> list[Check]:
    """Gemini platform via ADC: credentials present + a token can be minted (free, no generation)."""
    proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return [Check("cloud", "gemini platform (ADC)", OK, f"project {proj}, token ok",
                      "Live ephemeral tokens for apps need GEMINI_API_KEY")]
    except Exception as e:
        return [Check("cloud", "gemini platform (ADC)", FAIL, f"{type(e).__name__}",
                      "run: gcloud auth application-default login")]


def check_modal() -> list[Check]:
    if os.environ.get("MODAL_TOKEN_ID") or (Path.home() / ".modal.toml").exists():
        return [Check("cloud", "modal auth", OK, "token configured")]
    return [Check("cloud", "modal auth", WARN, "no token", "modal setup  (cloud role only)")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip network checks (cloud, Gemini)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    load_dotenv()
    checks = check_tools() + check_repo()
    broker_checks, broker_up = check_broker()
    checks += broker_checks
    if broker_up:
        checks += check_nodes()
    checks += check_modal()
    if not a.offline:
        checks += check_cloud() + check_sources() + check_gemini()
    if a.json:
        print(json.dumps([asdict(c) for c in checks], indent=2))
    else:
        section = None
        for c in checks:
            if c.section != section:
                section = c.section
                print(f"\n\033[1m{section}\033[0m")
            line = f"  {ICON[c.status]} {c.name:<18} {c.detail}"
            if c.fix and c.status != OK:
                line += f"\n       ↳ {c.fix}"
            print(line)
        n_fail = sum(c.status == FAIL for c in checks)
        n_warn = sum(c.status == WARN for c in checks)
        print(f"\n{n_fail} failing, {n_warn} warnings")
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
