"""Read-only runtime adapter for bounded memory retrieval.

This module is intentionally standalone and read-only:
- Opens SQLite with URI `mode=ro` (and `immutable=1` when supported).
- Never writes to SQLite.
- Never writes to JSONL event logs.
- Never imports the runtime (main/ui/actions/agent) or calls memory_engine.writer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data") / "jarvis_memory.db"

EXCLUDED_STATUSES = {"archived", "deprecated", "conflicted"}
INCLUDED_STATUSES = {"validated", "confirmed", "observed", "candidate"}

STATUS_PRIORITY = {"validated": 4, "confirmed": 3, "observed": 2, "candidate": 1}


def _safe_error(msg: str) -> str:
    # Avoid leaking raw sqlite errors into prompts/callers.
    return msg.strip()[:200]


def _db_uri_ro(db_path: Path) -> str:
    # Use file URI to safely handle spaces; request read-only and immutable when supported.
    return f"{db_path.resolve().as_uri()}?mode=ro&immutable=1"


def _connect_ro(db_path: str | Path) -> sqlite3.Connection | None:
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        return sqlite3.connect(_db_uri_ro(path), uri=True)
    except sqlite3.Error:
        # Some SQLite builds may not support immutable=1; retry with mode=ro only.
        try:
            return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error:
            return None


def _status_case_sql(column: str = "status") -> str:
    # Higher number = higher priority.
    return (
        f"CASE {column} "
        "WHEN 'validated' THEN 4 "
        "WHEN 'confirmed' THEN 3 "
        "WHEN 'observed' THEN 2 "
        "WHEN 'candidate' THEN 1 "
        "ELSE 0 END"
    )


def _fetch_memories(
    conn: sqlite3.Connection,
    *,
    memory_type: str | None = None,
    scopes: list[str] | None = None,
    project: str | None = None,
    query: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if memory_type:
        clauses.append("memory_type = ?")
        params.append(memory_type)

    if scopes:
        placeholders = ", ".join("?" for _ in scopes)
        clauses.append(f"scope IN ({placeholders})")
        params.extend(scopes)

    if project is not None:
        clauses.append("project = ?")
        params.append(project)

    # Status filtering.
    allowed = sorted(INCLUDED_STATUSES)
    placeholders = ", ".join("?" for _ in allowed)
    clauses.append(f"status IN ({placeholders})")
    params.extend(allowed)

    excluded = sorted(EXCLUDED_STATUSES)
    placeholders = ", ".join("?" for _ in excluded)
    clauses.append(f"status NOT IN ({placeholders})")
    params.extend(excluded)

    if query:
        clauses.append("content LIKE ?")
        params.append(f"%{query}%")

    where = " AND ".join(clauses) if clauses else "1=1"
    order_by = f"{_status_case_sql()} DESC, importance DESC, updated_at DESC"

    sql = (
        "SELECT id, memory_type, scope, project, content, status, importance, confidence, source, "
        "created_at, updated_at "
        f"FROM memories WHERE {where} ORDER BY {order_by} LIMIT ?"
    )
    params.append(int(limit))

    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _fetch_keyword_matches(
    conn: sqlite3.Connection,
    *,
    query: str,
    project: str | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    # First try strict separation: global scope and project scope.
    out = {"global": [], "project": []}
    out["global"] = _fetch_memories(conn, scopes=["global"], query=query, limit=limit)
    if project:
        scope = f"project:{project}"
        out["project"] = _fetch_memories(
            conn,
            scopes=[scope],
            project=project,
            query=query,
            limit=limit,
        )
    return out

def get_global_rules(limit: int = 8, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    ctx = load_runtime_memory_context(project=None, query=None, limit=limit, db_path=db_path)
    return ctx["global_rules"]


def get_project_context(
    project: str,
    limit: int = 8,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, list[dict[str, Any]]]:
    ctx = load_runtime_memory_context(project=project, query=None, limit=limit, db_path=db_path)
    return {
        "project_context": ctx["project_context"],
        "technical_state": ctx["technical_state"],
        "warnings": ctx["warnings"],
        "decisions": ctx["decisions"],
        "procedures": ctx["procedures"],
    }


def load_runtime_memory_context(
    project: str | None = None,
    query: str | None = None,
    limit: int = 8,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    base = {
        "global_rules": [],
        "project_context": [],
        "technical_state": [],
        "warnings": [],
        "decisions": [],
        "procedures": [],
        "keyword_matches": {"global": [], "project": []},
        "source_db": str(db_path),
        "available": False,
        "error": "",
    }

    conn = _connect_ro(db_path)
    if conn is None:
        path = Path(db_path)
        if not path.exists():
            base["available"] = False
            base["error"] = "memory db not found"
            return base
        base["available"] = False
        base["error"] = "could not open memory db read-only"
        return base

    try:
        base["available"] = True

        base["global_rules"] = _fetch_memories(
            conn,
            memory_type="GLOBAL_RULE",
            scopes=["global"],
            limit=limit,
        )

        if project:
            scope = f"project:{project}"
            base["project_context"] = _fetch_memories(
                conn,
                memory_type="PROJECT_CONTEXT",
                scopes=[scope],
                project=project,
                limit=limit,
            )
            base["technical_state"] = _fetch_memories(
                conn,
                memory_type="TECHNICAL_STATE",
                scopes=[scope],
                project=project,
                limit=limit,
            )
            # Warnings: project scope; optionally include global warnings if present.
            base["warnings"] = _fetch_memories(
                conn,
                memory_type="WARNING",
                scopes=[scope, "global"],
                limit=limit,
            )
            base["decisions"] = _fetch_memories(
                conn,
                memory_type="DECISION",
                scopes=[scope],
                project=project,
                limit=limit,
            )
            base["procedures"] = _fetch_memories(
                conn,
                memory_type="PROCEDURE",
                scopes=[scope],
                project=project,
                limit=limit,
            )

        if query:
            # Keep global/project separation. Keyword match does not filter by type.
            base["keyword_matches"] = _fetch_keyword_matches(
                conn,
                query=query,
                project=project,
                limit=limit,
            )
    except sqlite3.Error:
        base["available"] = False
        base["error"] = "read-only query failed"
        base["global_rules"] = []
        base["project_context"] = []
        base["technical_state"] = []
        base["warnings"] = []
        base["decisions"] = []
        base["procedures"] = []
        base["keyword_matches"] = {"global": [], "project": []}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return base


def _format_lines(title: str, items: list[dict[str, Any]], max_items: int) -> list[str]:
    if not items:
        return [f"{title}:", "- (none)"]
    lines = [f"{title}:"]
    for item in items[:max_items]:
        content = (item.get("content") or "").strip().replace("\n", " ")
        if len(content) > 220:
            content = content[:217].rstrip() + "..."
        lines.append(f"- {content}")
    return lines


def format_memory_context_for_prompt(context: dict, max_chars: int = 3000) -> str:
    if not context or not context.get("available"):
        return ""

    sections: list[str] = ["[READ-ONLY MEMORY CONTEXT]"]
    limit = 8

    sections.extend(_format_lines("Global Rules", context.get("global_rules", []), limit))
    if context.get("project_context"):
        sections.extend(_format_lines("Project Context", context.get("project_context", []), limit))
    if context.get("technical_state"):
        sections.extend(_format_lines("Technical State", context.get("technical_state", []), limit))
    if context.get("warnings"):
        sections.extend(_format_lines("Warnings", context.get("warnings", []), limit))
    if context.get("decisions"):
        sections.extend(_format_lines("Decisions", context.get("decisions", []), limit))
    if context.get("procedures"):
        sections.extend(_format_lines("Procedures", context.get("procedures", []), limit))

    matches = context.get("keyword_matches") or {}
    global_matches = matches.get("global") or []
    project_matches = matches.get("project") or []
    if global_matches or project_matches:
        sections.extend(_format_lines("Keyword Matches (Global)", global_matches, limit))
        if project_matches:
            sections.extend(_format_lines("Keyword Matches (Project)", project_matches, limit))

    sections.append("[/READ-ONLY MEMORY CONTEXT]")

    out = "\n".join(sections).strip()
    if len(out) <= max_chars:
        return out + "\n"

    # Hard bound without breaking the end marker.
    end = "\n[/READ-ONLY MEMORY CONTEXT]\n"
    head_max = max(0, max_chars - len(end))
    trimmed = out[:head_max].rstrip()
    if not trimmed.endswith("..."):
        trimmed = trimmed[: max(0, head_max - 3)].rstrip() + "..."
    return trimmed + end
