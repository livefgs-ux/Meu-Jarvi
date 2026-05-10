"""Retrieval operations for the local memory engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import DEFAULT_DB_PATH, init_db, open_db
from .schemas import MemoryRecord


STATUS_ORDER_SQL = """
CASE status
    WHEN 'validated' THEN 6
    WHEN 'confirmed' THEN 5
    WHEN 'observed' THEN 4
    WHEN 'candidate' THEN 3
    WHEN 'conflicted' THEN 2
    WHEN 'deprecated' THEN 1
    WHEN 'archived' THEN 0
    ELSE 0
END DESC,
importance DESC,
updated_at DESC
"""


def _record_from_row(row) -> MemoryRecord:
    metadata = json.loads(row["metadata_json"] or "{}")
    return MemoryRecord(
        memory_id=row["id"],
        memory_type=row["memory_type"],
        scope=row["scope"],
        project=row["project"],
        content=row["content"],
        status=row["status"],
        importance=row["importance"],
        confidence=row["confidence"],
        source=row["source"],
        metadata=metadata,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_memory_by_id(memory_id: int, *, db_path: str | Path = DEFAULT_DB_PATH) -> MemoryRecord | None:
    init_db(db_path)
    with open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return _record_from_row(row) if row else None


def search_memories(
    *,
    query: str | None = None,
    memory_type: str | None = None,
    scope: str | None = None,
    project: str | None = None,
    status: str | None = None,
    include_archived: bool = False,
    limit: int = 20,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[MemoryRecord]:
    init_db(db_path)
    clauses = []
    params: list[Any] = []

    if query:
        clauses.append("content LIKE ?")
        params.append(f"%{query}%")
    if memory_type:
        clauses.append("memory_type = ?")
        params.append(memory_type.upper())
    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    if project:
        clauses.append("project = ?")
        params.append(project)
    if status:
        clauses.append("status = ?")
        params.append(status.lower())
    if not include_archived:
        clauses.append("status NOT IN ('archived', 'deprecated')")

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    sql = f"SELECT * FROM memories {where} ORDER BY {STATUS_ORDER_SQL} LIMIT ?"
    params.append(int(limit))

    with open_db(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_record_from_row(row) for row in rows]


def list_memories_by_scope(scope: str, *, db_path: str | Path = DEFAULT_DB_PATH) -> list[MemoryRecord]:
    return search_memories(scope=scope, db_path=db_path, limit=100)


def list_active_global_rules(*, db_path: str | Path = DEFAULT_DB_PATH) -> list[MemoryRecord]:
    return search_memories(
        memory_type="GLOBAL_RULE",
        scope="global",
        db_path=db_path,
        limit=100,
    )


def list_project_context(project: str, *, db_path: str | Path = DEFAULT_DB_PATH) -> list[MemoryRecord]:
    scope = f"project:{project}"
    return search_memories(scope=scope, db_path=db_path, limit=100)


def retrieve_context(
    *,
    project: str | None = None,
    task: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, list[MemoryRecord]]:
    context = {
        "global_rules": list_active_global_rules(db_path=db_path),
        "project_context": [],
        "task_context": [],
        "procedures": search_memories(memory_type="PROCEDURE", db_path=db_path, limit=20),
        "decisions": search_memories(memory_type="DECISION", db_path=db_path, limit=20),
        "warnings": search_memories(memory_type="WARNING", db_path=db_path, limit=20),
    }
    if project:
        context["project_context"] = list_project_context(project, db_path=db_path)
    if task:
        context["task_context"] = search_memories(query=task, db_path=db_path, limit=10)
    return context
