"""Structured JSONL event logging with a human-readable mirror on stdout."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class EventLogger:
    """Append-only event stream: one JSON object per line, mirrored to stdout."""

    def __init__(self, path: Path, run_id: str, stage: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")
        self.path = path
        self.run_id = run_id
        self.stage = stage
        self._t0 = time.monotonic()

    def emit(self, event: str, level: str = "info", **fields: Any) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "elapsed_s": round(time.monotonic() - self._t0, 3),
            "run_id": self.run_id,
            "stage": self.stage,
            "level": level,
            "event": event,
            **fields,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()
        extra = " ".join(f"{k}={_short(v)}" for k, v in fields.items())
        print(f"[{record['elapsed_s']:9.3f}s] {level.upper():5s} {self.stage}:{event} {extra}", flush=True)

    def info(self, event: str, **fields: Any) -> None:
        self.emit(event, "info", **fields)

    def warn(self, event: str, **fields: Any) -> None:
        self.emit(event, "warn", **fields)

    def error(self, event: str, **fields: Any) -> None:
        self.emit(event, "error", **fields)

    def metric(self, name: str, value: Any, **fields: Any) -> None:
        self.emit("metric", "info", name=name, value=value, **fields)

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()
