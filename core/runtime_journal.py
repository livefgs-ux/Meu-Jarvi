import os
import time
import logging
from typing import Optional, Dict, Any, List
from core.event_timeline import EventTimeline, EventRecord, DEFAULT_TIMELINE_PATH

# Singleton instance
_RUNTIME_TIMELINE = EventTimeline(max_events=1000)

def get_runtime_timeline() -> EventTimeline:
    return _RUNTIME_TIMELINE

def record_event(
    event_type: str,
    source: str,
    summary: str,
    metadata: Optional[Dict[str, Any]] = None,
    severity: str = "info",
    correlation_id: Optional[str] = None
) -> Optional[EventRecord]:
    """
    Records an event to the runtime timeline. Fail-open.
    """
    try:
        return _RUNTIME_TIMELINE.add_event(
            event_type=event_type,
            source=source,
            summary=summary,
            metadata=metadata,
            severity=severity,
            correlation_id=correlation_id
        )
    except Exception as e:
        # Fail-open: log error but don't crash
        logging.error(f"[runtime_journal] Failed to record event: {e}")
        return None

def list_recent_events(limit: int = 20) -> List[EventRecord]:
    return _RUNTIME_TIMELINE.list_recent(limit=limit)

def export_runtime_events(path: Optional[str] = None):
    if path is None:
        path = DEFAULT_TIMELINE_PATH

    try:
        # Ensure directory exists only in real runtime
        # (Tests should use explicit paths or tempdirs)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _RUNTIME_TIMELINE.export_jsonl(path)
    except Exception as e:
        logging.error(f"[runtime_journal] Failed to export timeline: {e}")
