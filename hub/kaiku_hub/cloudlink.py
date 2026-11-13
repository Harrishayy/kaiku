"""Cloud -> hub: command polling, nudge lookup, node-health reporting. All fail soft (timeouts, no raise)."""

from __future__ import annotations

import asyncio
import random
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from kaiku_contracts import ContractError, Envelope, validate
from kaiku_contracts.api import NodeHealthReport, NudgeResponse
from kaiku_contracts.jlog import get_logger
from kaiku_contracts.payloads import NUDGE_ARMS

log = get_logger("hub")


class CloudLink:
    def __init__(self, *, url: str | None, home_id: str, token: str | None = None, timeout_s: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.url = url.rstrip("/") if url else None
        self.home_id = home_id
        self.token = token
        self.timeout_s = timeout_s
        self.transport = transport
        self.since: str | None = None
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.last_error: str | None = None

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.AsyncClient(base_url=self.url or "", headers=headers, timeout=timeout or self.timeout_s,
                                 transport=self.transport)

    async def get_nudge(self, timeout_s: float = 3.0) -> NudgeResponse | None:
        if not self.url:
            return None
        try:
            async with self._client(timeout_s) as c:
                r = await c.get("/v1/nudge", params={"home_id": self.home_id})
                r.raise_for_status()
                return NudgeResponse.model_validate(r.json())
        except Exception as e:
            self.last_error = f"nudge: {type(e).__name__}: {e}"
            log.warning("nudge_fallback", self.last_error)
            return None

    async def companion_session(self, intent: str = "ritual", timeout_s: float = 4.0) -> dict[str, Any] | None:
        """POST /v1/companion/session {surface: robot, home_id, intent} -> {system_instruction, tools, model, voice,
        ...} (plan 03 §3). None when the cloud is offline or doesn't have the endpoint yet (404): the caller falls
        back to the local SYSTEM_PROMPT + live/tools.py."""
        if not self.url:
            return None
        try:
            async with self._client(timeout_s) as c:
                r = await c.post("/v1/companion/session",
                                 json={"surface": "robot", "home_id": self.home_id, "intent": intent})
            if r.status_code != 200:
                log.info("companion_session_fallback", f"HTTP {r.status_code}")
                return None
            data = r.json()
        except Exception as e:
            log.info("companion_session_fallback", f"{type(e).__name__}")
            return None
        if not isinstance(data, dict) or not isinstance(data.get("system_instruction"), str):
            log.warning("companion_session_fallback", "response without system_instruction")
            return None
        return data

    async def companion_tool(self, name: str, args: dict[str, Any], session_id: str | None = None,
                             timeout_s: float = 4.0) -> dict[str, Any] | None:
        """Forward a cloud-executed tool call (remember/forget/recall/suggest_nudge/end_session) to
        POST /v1/companion/tool. None when offline: the caller tells the model the tool is unavailable."""
        if not self.url:
            return None
        try:
            async with self._client(timeout_s) as c:
                r = await c.post("/v1/companion/tool", json={"home_id": self.home_id, "surface": "robot",
                                                             "session_id": session_id, "name": name, "args": args})
            if r.status_code != 200:
                log.info("companion_tool_unavailable", f"HTTP {r.status_code}", tool=name)
                return None
            return r.json()
        except Exception as e:
            log.info("companion_tool_unavailable", type(e).__name__, tool=name)
            return None

    async def poll_commands(self) -> list[Envelope[Any]]:
        if not self.url:
            return []
        params = {"home_id": self.home_id}
        if self.since:
            params["since"] = self.since
        try:
            async with self._client() as c:
                r = await c.get("/v1/commands", params=params)
                r.raise_for_status()
                raw = r.json().get("commands", [])
        except Exception as e:
            self.last_error = f"commands: {type(e).__name__}: {e}"
            return []
        out: list[Envelope[Any]] = []
        for item in raw:
            try:
                env = validate(item)
            except ContractError as e:
                log.warning("bad_command", str(e)[:200])
                continue
            if env.type != "cmd.hub" or env.home_id != self.home_id or str(env.id) in self._seen:
                continue
            self._seen[str(env.id)] = None
            while len(self._seen) > 1000:
                self._seen.popitem(last=False)
            out.append(env)
            ts = item.get("ts")
            if ts and (self.since is None or ts > self.since):
                self.since = ts
        return out

    async def report_health(self, nodes: dict[str, dict], uplink_queue: int, uplink_lag_s: float | None) -> bool:
        if not self.url:
            return False
        try:
            report = NodeHealthReport(nodes=nodes, uplink_queue=uplink_queue, uplink_lag_s=uplink_lag_s,
                                      reported_at=datetime.now(UTC))
            async with self._client() as c:
                r = await c.put(f"/v1/health/{self.home_id}", json=report.model_dump(mode="json"))
                return r.status_code < 300
        except Exception as e:
            self.last_error = f"health: {type(e).__name__}: {e}"
            return False

    async def run(
        self,
        on_command: Callable[[Envelope[Any]], Awaitable[None]],
        health: Callable[[], tuple[dict[str, dict], int, float | None]],
        poll_s: float = 3.0,
        health_s: float = 10.0,
    ) -> None:
        if not self.url:
            return
        last_health = 0.0
        loop = asyncio.get_running_loop()
        while True:
            for env in await self.poll_commands():
                try:
                    await on_command(env)
                except Exception as e:
                    log.error("command_failed", str(e))
            if loop.time() - last_health >= health_s:
                last_health = loop.time()
                await self.report_health(*health())
            await asyncio.sleep(poll_s)


def local_nudge(suggested: str | None = None) -> tuple[str, str]:
    """Offline fallback: clinician suggestion if any, else uniform random (bandit cold start)."""
    if suggested in NUDGE_ARMS:
        return suggested, "Suggested by your care team."
    return random.choice(NUDGE_ARMS), "Trying something new today."
