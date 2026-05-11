"""Runtime wrapper for inserting bounded read-only memory context.

Design goals:
- Thin wrapper around memory_engine.runtime_adapter (read-only SQLite).
- OFF by default.
- Never writes to SQLite or JSONL.
- Never imports runtime modules (main/ui/actions/agent) or tools.
"""

from __future__ import annotations

import os
from pathlib import Path

from .runtime_adapter import (
    DEFAULT_DB_PATH,
    format_memory_context_for_prompt,
    load_runtime_memory_context,
)


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_int(value: str | None, default: int) -> int:
    try:
        n = int((value or "").strip())
        if n <= 0:
            return default
        return n
    except Exception:
        return default


def build_readonly_memory_context(
    *,
    enabled: bool = False,
    project: str | None = None,
    query: str | None = None,
    max_chars: int = 2500,
    limit: int = 8,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str:
    """Return bounded [READ-ONLY MEMORY CONTEXT] prompt block or empty string.

    - If disabled, returns "".
    - If enabled but project is missing/empty, returns "" (do not guess project).
    - If DB missing/unavailable, returns "".
    - Never raises raw sqlite errors.
    """
    if not enabled:
        return ""

    proj = (project or "").strip()
    if not proj:
        return ""

    try:
        ctx = load_runtime_memory_context(project=proj, query=query, limit=int(limit), db_path=db_path)
        if not ctx.get("available"):
            return ""
        text = format_memory_context_for_prompt(ctx, max_chars=int(max_chars))
        return text or ""
    except Exception:
        return ""


def build_readonly_memory_context_from_env(
    *,
    environ: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Build read-only memory prompt block using an env toggle contract.

    Toggle:
      JARVIS_READONLY_MEMORY: enabled only for 1/true/yes/on (case-insensitive)

    Optional:
      JARVIS_MEMORY_PROJECT
      JARVIS_MEMORY_MAX_CHARS
      JARVIS_MEMORY_LIMIT
      JARVIS_MEMORY_DB

    Safety:
    - Default OFF.
    - If enabled but missing project, returns "".
    - Invalid numeric env values fall back safely to defaults.
    - db_path argument overrides env DB path (for tests).
    """
    env = environ if environ is not None else os.environ
    if not _truthy(env.get("JARVIS_READONLY_MEMORY")):
        return ""

    project = (env.get("JARVIS_MEMORY_PROJECT") or "").strip()
    if not project:
        return ""

    max_chars = _safe_int(env.get("JARVIS_MEMORY_MAX_CHARS"), 2500)
    limit = _safe_int(env.get("JARVIS_MEMORY_LIMIT"), 8)

    if db_path is not None:
        resolved_db = db_path
    else:
        resolved_db = env.get("JARVIS_MEMORY_DB") or DEFAULT_DB_PATH

    query = (env.get("JARVIS_MEMORY_QUERY") or "").strip() or None

    return build_readonly_memory_context(
        enabled=True,
        project=project,
        query=query,
        max_chars=max_chars,
        limit=limit,
        db_path=resolved_db,
    )

