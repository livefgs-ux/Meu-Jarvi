"""Write operations for the local memory engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .conflict_resolver import detect_potential_conflicts
from .database import DEFAULT_DB_PATH, init_db, open_db
from .event_log import DEFAULT_EVENT_LOG_PATH, append_event
from .privacy_guard import assert_content_safe
from .schemas import (
    MemoryRecord,
    normalize_memory_type,
    normalize_status,
    utc_now,
    validate_confidence,
    validate_content,
    validate_importance,
    validate_memory_scope_policy,
    validate_scope,
)


def _insert_event_row(conn, event_type: str, summary: str, source: str, memory_id: int | None) -> None:
    conn.execute(
        """
        INSERT INTO events(event_type, summary, source, related_memory_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_type, summary, source or "manual", memory_id, utc_now()),
    )


def create_memory(
    memory_type: str,
    scope: str,
    content: str,
    *,
    status: str = "observed",
    importance: int = 5,
    confidence: float = 0.5,
    source: str = "manual",
    project: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    event_log_path: str | Path = DEFAULT_EVENT_LOG_PATH,
) -> MemoryRecord:
    record = MemoryRecord(
        memory_type=memory_type,
        scope=scope,
        content=content,
        status=status,
        importance=importance,
        confidence=confidence,
        source=source,
        project=project,
        metadata=metadata or {},
    ).validated()
    assert_content_safe(record.content)

    init_db(db_path)
    with open_db(db_path) as conn:
        conflicts = detect_potential_conflicts(
            conn,
            record.memory_type,
            record.scope,
            record.content,
        )
        if conflicts and record.status in {"observed", "candidate"}:
            record.status = "conflicted"

        now = utc_now()
        record.created_at = now
        record.updated_at = now
        cur = conn.execute(
            """
            INSERT INTO memories(
                memory_type, scope, project, content, status, importance,
                confidence, source, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.memory_type,
                record.scope,
                record.project,
                record.content,
                record.status,
                record.importance,
                record.confidence,
                record.source,
                json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                record.created_at,
                record.updated_at,
            ),
        )
        record.memory_id = int(cur.lastrowid)
        _insert_event_row(conn, "memory_created", record.content[:160], record.source, record.memory_id)
        conn.commit()

    append_event(
        "memory_created",
        record.content[:160],
        record.source,
        related_memory_id=record.memory_id,
        event_log_path=event_log_path,
        extra={"memory_type": record.memory_type, "scope": record.scope, "status": record.status},
    )
    return record


def update_memory_status(
    memory_id: int,
    status: str,
    *,
    source: str = "manual",
    db_path: str | Path = DEFAULT_DB_PATH,
    event_log_path: str | Path = DEFAULT_EVENT_LOG_PATH,
) -> MemoryRecord:
    new_status = normalize_status(status)
    init_db(db_path)
    with open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            raise KeyError(f"Memory not found: {memory_id}")
        updated_at = utc_now()
        conn.execute(
            "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, updated_at, memory_id),
        )
        _insert_event_row(conn, "memory_status_updated", f"Status changed to {new_status}", source, memory_id)
        conn.commit()

    append_event(
        "memory_status_updated",
        f"Status changed to {new_status}",
        source,
        related_memory_id=memory_id,
        event_log_path=event_log_path,
    )
    from .retriever import get_memory_by_id

    record = get_memory_by_id(memory_id, db_path=db_path)
    if record is None:
        raise KeyError(f"Memory not found after update: {memory_id}")
    return record


def archive_memory(
    memory_id: int,
    *,
    source: str = "manual",
    db_path: str | Path = DEFAULT_DB_PATH,
    event_log_path: str | Path = DEFAULT_EVENT_LOG_PATH,
) -> MemoryRecord:
    return update_memory_status(
        memory_id,
        "archived",
        source=source,
        db_path=db_path,
        event_log_path=event_log_path,
    )


def validate_write_inputs(memory_type: str, scope: str, content: str, status: str, importance: int, confidence: float) -> None:
    normalized_type = normalize_memory_type(memory_type)
    normalized_scope = validate_scope(scope)
    validate_memory_scope_policy(normalized_type, normalized_scope)
    validate_content(content)
    normalize_status(status)
    validate_importance(importance)
    validate_confidence(confidence)
