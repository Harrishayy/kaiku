"""Structured JSON-lines logging to stdout: {"ts","node","level","event","msg",...context}.

Never log secrets, raw audio, images or transcripts.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any


class _JsonFormatter(logging.Formatter):
    def __init__(self, node: str):
        super().__init__()
        self.node = node

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "node": self.node,
            "level": record.levelname.lower(),
            "event": getattr(record, "event", record.name),
            "msg": record.getMessage(),
        }
        out.update(getattr(record, "ctx", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class NodeLogger:
    """logger.info("ppg_window", "clean beats 82%", clean=0.82)"""

    def __init__(self, node: str):
        self.node = node
        self._log = logging.getLogger(f"kaiku.{node}")
        if not self._log.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(_JsonFormatter(node))
            self._log.addHandler(h)
            self._log.propagate = False
        self._log.setLevel(os.environ.get("KAIKU_LOG_LEVEL", "INFO").upper())

    def _emit(self, level: int, event: str, msg: str = "", exc_info: bool = False, **ctx: Any) -> None:
        self._log.log(level, msg, extra={"event": event, "ctx": ctx}, exc_info=exc_info)

    def debug(self, event: str, msg: str = "", **ctx: Any) -> None:
        self._emit(logging.DEBUG, event, msg, **ctx)

    def info(self, event: str, msg: str = "", **ctx: Any) -> None:
        self._emit(logging.INFO, event, msg, **ctx)

    def warning(self, event: str, msg: str = "", **ctx: Any) -> None:
        self._emit(logging.WARNING, event, msg, **ctx)

    def error(self, event: str, msg: str = "", exc_info: bool = False, **ctx: Any) -> None:
        self._emit(logging.ERROR, event, msg, exc_info=exc_info, **ctx)


def get_logger(node: str) -> NodeLogger:
    return NodeLogger(node)
