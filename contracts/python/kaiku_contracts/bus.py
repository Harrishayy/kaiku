"""Async MQTT bus client shared by hub, sims and tools (requires `aiomqtt`).

- validates every publish and every received message against the contracts
- reconnects forever with backoff (a dead broker never crashes a node)
- publishes a retained heartbeat on health/<node> every 5 s, and "down" as last will

    bus = Bus("head", sim=True)
    bus.on("cmd/head", handle_cmd)            # handler(topic: ParsedTopic, env: Envelope)
    async with bus:
        await bus.publish("raw.head.tap", {"t_ms": 1, "force": 1.2})
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from .envelope import Envelope, Source, default_home_id, make
from .jlog import get_logger
from .registry import ContractError, to_json, validate
from .topics import ParsedTopic, parse_topic, qos_for, retain_for, topic, topic_for

Handler = Callable[[ParsedTopic, Envelope[Any]], Awaitable[None]]
HEARTBEAT_S = 5.0


class Bus:
    def __init__(
        self,
        node: Source,
        *,
        home_id: str | None = None,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        version: str = "0.1.0",
        sim: bool = False,
        heartbeat: bool = True,
        details: Callable[[], dict[str, Any]] | None = None,
    ):
        self.node = node
        self.home_id = home_id or default_home_id()
        self.host = host or os.environ.get("MQTT_HOST", "localhost")
        self.port = int(port or os.environ.get("MQTT_PORT", 1883))
        self.username = username or os.environ.get("MQTT_USER") or None
        self.password = password or os.environ.get("MQTT_PASS") or None
        self.version = version
        self.sim = sim
        self.heartbeat = heartbeat
        self.details = details
        self.status: str = "ok"
        self.last_error: str | None = None
        self.connected = asyncio.Event()
        self.log = get_logger(node)
        self._handlers: list[tuple[str, Handler]] = []
        self._client: Any = None
        self._task: asyncio.Task | None = None
        self._started = time.monotonic()
        self._dropped = 0

    # ------------------------------------------------------------------ setup
    def on(self, pattern: str, handler: Handler, *, home_id: str | None = None) -> None:
        """Subscribe to `pattern` relative to this home, e.g. "cmd/head" or "raw/sensors/#".
        Pass home_id="+" to listen to all homes."""
        self._handlers.append((topic(home_id or self.home_id, *pattern.split("/", 1)), handler))  # type: ignore[arg-type]

    def set_status(self, status: str, error: str | None = None) -> None:
        self.status = status
        if error:
            self.last_error = error

    async def __aenter__(self) -> Bus:
        self._task = asyncio.create_task(self._run(), name=f"bus-{self.node}")
        try:
            await asyncio.wait_for(self.connected.wait(), timeout=3)
        except TimeoutError:
            self.log.warning("bus_not_connected", f"broker {self.host}:{self.port} not reachable yet; retrying in background")
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None and self.heartbeat:
            try:
                await self._publish_health("down")
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------ publish
    async def publish(
        self,
        type_: str,
        payload: BaseModel | dict[str, Any],
        *,
        source: Source | None = None,
        quality: float | None = None,
        sim: bool | None = None,
    ) -> Envelope[Any]:
        """Validate + publish. Raises ContractError on a bad payload. Drops (with a log) if offline."""
        env = make(type_, payload, source=source or self.node, home_id=self.home_id, quality=quality,
                   sim=self.sim if sim is None else sim)
        await self.publish_env(env)
        return env

    async def publish_env(self, env: Envelope[Any]) -> bool:
        validate(env)  # never put an invalid message on the bus
        client = self._client
        if client is None:
            self._dropped += 1
            if self._dropped in (1, 10, 100) or self._dropped % 1000 == 0:
                self.log.warning("bus_offline_drop", f"dropped {self._dropped} messages while offline", type=env.type)
            return False
        try:
            await client.publish(topic_for(env), to_json(env), qos=qos_for(env), retain=retain_for(env))
            return True
        except Exception as e:  # broker went away mid-publish
            self._dropped += 1
            self.log.warning("bus_publish_failed", str(e), type=env.type)
            return False

    async def _publish_health(self, status: str | None = None) -> None:
        payload = {
            "status": status or self.status,
            "version": self.version,
            "uptime_s": round(time.monotonic() - self._started, 1),
            "last_error": self.last_error,
            "details": {"dropped": self._dropped, **(self.details() if self.details else {})},
        }
        await self.publish("health", payload)

    # ------------------------------------------------------------------ loop
    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await self._publish_health()
            except Exception as e:
                self.log.warning("heartbeat_failed", str(e))
            await asyncio.sleep(HEARTBEAT_S)

    async def _run(self) -> None:
        import aiomqtt  # imported lazily so contracts don't hard-depend on it

        backoff = 1.0
        will_payload = to_json(make("health", {"status": "down", "version": self.version, "uptime_s": 0,
                                               "last_error": "connection lost"},
                                    source=self.node, home_id=self.home_id, sim=self.sim))
        will = aiomqtt.Will(topic(self.home_id, "health", self.node), will_payload, qos=1, retain=True)
        while True:
            hb: asyncio.Task | None = None
            try:
                async with aiomqtt.Client(
                    self.host, self.port, username=self.username, password=self.password,
                    identifier=f"kaiku-{self.node}-{secrets.token_hex(3)}", will=will, keepalive=15,
                ) as client:
                    self._client = client
                    backoff = 1.0
                    for pattern, _ in self._handlers:
                        await client.subscribe(pattern, qos=1)
                    self.connected.set()
                    self.log.info("bus_connected", f"{self.host}:{self.port}", subscriptions=[p for p, _ in self._handlers])
                    if self.heartbeat:
                        hb = asyncio.create_task(self._heartbeat_loop())
                    async for m in client.messages:
                        await self._dispatch(str(m.topic), m.payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.log.warning("bus_disconnected", f"{type(e).__name__}: {e}; retry in {backoff:.0f}s")
            finally:
                self._client = None
                self.connected.clear()
                if hb:
                    hb.cancel()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _dispatch(self, t: str, raw: Any) -> None:
        import aiomqtt

        try:
            env = validate(raw)
            parsed = parse_topic(t)
        except (ContractError, ValueError) as e:
            self.log.warning("contract_violation", str(e)[:300], topic=t)
            return
        for pattern, handler in self._handlers:
            if aiomqtt.Topic(t).matches(pattern):
                try:
                    await handler(parsed, env)
                except Exception as e:  # a bad handler must not kill the node
                    self.last_error = f"{type(e).__name__}: {e}"
                    self.log.error("handler_failed", self.last_error, topic=t, exc_info=True)
