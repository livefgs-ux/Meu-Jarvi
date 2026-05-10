"""Simple v0 conflict detection for memory records."""

from __future__ import annotations

import re
import sqlite3


def _keywords(content: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_+\-.]{3,}", (content or "").lower())
    stop = {"the", "and", "that", "this", "with", "from", "para", "como", "uma", "que"}
    return {word for word in words if word not in stop}


def keyword_overlap(left: str, right: str) -> float:
    a = _keywords(left)
    b = _keywords(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def detect_potential_conflicts(
    conn: sqlite3.Connection,
    memory_type: str,
    scope: str,
    content: str,
    threshold: float = 0.6,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, memory_type, scope, content, status, importance, confidence, source,
               project, metadata_json, created_at, updated_at
        FROM memories
        WHERE memory_type = ?
          AND scope = ?
          AND status NOT IN ('archived', 'deprecated')
        """,
        (memory_type, scope),
    ).fetchall()

    conflicts = []
    normalized = " ".join((content or "").lower().split())
    for row in rows:
        existing = " ".join((row["content"] or "").lower().split())
        if existing == normalized:
            continue
        overlap = keyword_overlap(existing, normalized)
        if overlap >= threshold:
            item = dict(row)
            item["overlap"] = overlap
            conflicts.append(item)
    return conflicts
