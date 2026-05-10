"""Schemas and validation helpers for the local memory engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


MEMORY_TYPES = {
    "GLOBAL_RULE",
    "PREFERENCE",
    "CORRECTION",
    "PROJECT_CONTEXT",
    "TECHNICAL_STATE",
    "DECISION",
    "PROCEDURE",
    "WARNING",
    "IDEA",
    "TASK",
    "SESSION_SUMMARY",
}

MEMORY_STATUSES = {
    "observed",
    "candidate",
    "confirmed",
    "validated",
    "conflicted",
    "deprecated",
    "archived",
}

ARCHIVED_STATUSES = {"archived", "deprecated"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_memory_type(memory_type: str) -> str:
    value = (memory_type or "").strip().upper()
    if value not in MEMORY_TYPES:
        raise ValueError(f"Invalid memory type: {memory_type!r}")
    return value


def normalize_status(status: str) -> str:
    value = (status or "").strip().lower()
    if value not in MEMORY_STATUSES:
        raise ValueError(f"Invalid memory status: {status!r}")
    return value


def validate_scope(scope: str) -> str:
    value = (scope or "").strip()
    if value == "global" or value in {"session", "temporary"}:
        return value
    if value.startswith("project:") and value.split(":", 1)[1].strip():
        return value
    raise ValueError(f"Invalid memory scope: {scope!r}")


def validate_memory_scope_policy(memory_type: str, scope: str) -> None:
    normalized_type = normalize_memory_type(memory_type)
    normalized_scope = validate_scope(scope)

    if normalized_type == "GLOBAL_RULE" and normalized_scope != "global":
        raise ValueError("GLOBAL_RULE memories must use scope='global'")

    if normalized_type in {"PROJECT_CONTEXT", "TECHNICAL_STATE"} and normalized_scope == "global":
        raise ValueError(
            f"{normalized_type} memories cannot use scope='global'; "
            "use project:<name>, session, or temporary"
        )


def validate_importance(importance: int) -> int:
    try:
        value = int(importance)
    except (TypeError, ValueError) as exc:
        raise ValueError("Importance must be an integer from 1 to 10") from exc
    if not 1 <= value <= 10:
        raise ValueError("Importance must be from 1 to 10")
    return value


def validate_confidence(confidence: float) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("Confidence must be a float from 0.0 to 1.0") from exc
    if not 0.0 <= value <= 1.0:
        raise ValueError("Confidence must be from 0.0 to 1.0")
    return value


def validate_content(content: str) -> str:
    value = (content or "").strip()
    if not value:
        raise ValueError("Memory content cannot be empty")
    return value


@dataclass(slots=True)
class MemoryRecord:
    memory_type: str
    scope: str
    content: str
    status: str = "observed"
    importance: int = 5
    confidence: float = 0.5
    source: str = "manual"
    project: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    memory_id: int | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def validated(self) -> "MemoryRecord":
        self.memory_type = normalize_memory_type(self.memory_type)
        self.scope = validate_scope(self.scope)
        validate_memory_scope_policy(self.memory_type, self.scope)
        self.status = normalize_status(self.status)
        self.importance = validate_importance(self.importance)
        self.confidence = validate_confidence(self.confidence)
        self.content = validate_content(self.content)
        self.source = (self.source or "manual").strip()
        return self
