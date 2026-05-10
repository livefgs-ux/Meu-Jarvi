"""Append-only JSONL audit log for memory events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import utc_now


DEFAULT_EVENT_LOG_PATH = Path("data") / "raw_events.jsonl"


def append_event(
    event_type: str,
    summary: str,
    source: str,
    related_memory_id: int | None = None,
    event_log_path: str | Path = DEFAULT_EVENT_LOG_PATH,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(event_log_path)
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "timestamp": utc_now(),
        "event_type": event_type,
        "summary": summary,
        "source": source or "manual",
        "related_memory_id": related_memory_id,
    }
    if extra:
        event["extra"] = extra

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event
