"""Message envelope shared by every Kaiku message (MQTT and HTTPS).

`type` is fully qualified and determines the MQTT topic:
    obs.<name>            -> kaiku/v1/<home>/obs/<name>
    raw.<source>.<stream> -> kaiku/v1/<home>/raw/<source>/<stream>
    cmd.<target>          -> kaiku/v1/<home>/cmd/<target>
    health                -> kaiku/v1/<home>/health/<envelope.source>
    log                   -> kaiku/v1/<home>/log/<envelope.source>
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

SCHEMA_VERSION = 1

# "phone" = the iPhone app (KaikuKit): wearable_daily, weather-check self_report, play_session. "laptop" = Mac app
# + browser apps.
Source = Literal["head", "sensors", "hub", "friendlink", "glasses", "laptop", "phone", "cloud", "sim"]
SOURCES: tuple[str, ...] = ("head", "sensors", "hub", "friendlink", "glasses", "laptop", "phone", "cloud", "sim")

P = TypeVar("P")


def uuid7() -> UUID:
    """Time-ordered UUIDv7 (RFC 9562). Used as the idempotency key."""
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    value = (ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand & 0x3FFF_FFFF_FFFF_FFFF  # rand_b (62 bits)
    return UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Envelope(BaseModel, Generic[P]):
    model_config = ConfigDict(extra="forbid")

    v: Literal[1] = 1
    id: UUID = Field(default_factory=uuid7)
    ts: datetime = Field(default_factory=utcnow)
    home_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    source: Source
    type: str = Field(min_length=1)
    payload: P
    quality: float | None = Field(default=None, ge=0, le=1)
    sim: bool = False

    @field_serializer("ts")
    def _ser_ts(self, ts: datetime) -> str:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def default_home_id() -> str:
    return os.environ.get("KAIKU_HOME_ID", "demo-aino")


def make(
    type: str,
    payload: BaseModel | dict[str, Any],
    *,
    source: Source,
    home_id: str | None = None,
    quality: float | None = None,
    sim: bool = False,
    ts: datetime | None = None,
) -> Envelope[Any]:
    """Build an envelope and validate the payload against the registered model.

    Raises `ContractError` if the payload does not match the contract.
    """
    from .registry import validate  # local import: registry imports this module

    data = payload.model_dump(mode="json", exclude_none=True) if isinstance(payload, BaseModel) else payload
    raw = {
        "home_id": home_id or default_home_id(),
        "source": source,
        "type": type,
        "payload": data,
        "quality": quality,
        "sim": sim,
    }
    if ts is not None:
        raw["ts"] = ts
    return validate(raw)
