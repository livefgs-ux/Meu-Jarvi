"""Deterministic policy: should a save_memory candidate be stored?

Read-only with respect to persistence: no SQLite, no writer, no runtime hooks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .privacy_guard import check_content_safe


@dataclass(frozen=True, slots=True)
class MemoryDecision:
    should_save: bool
    reason: str
    memory_type: str | None
    scope: str | None
    project: str | None
    requires_review: bool
    confidence: float
    normalized_content: str


_LOW_SIGNAL_PHRASES: frozenset[str] = frozenset(
    {
        "ok",
        "sim",
        "não",
        "nao",
        "talvez",
        "haha",
        "obrigado",
        "valeu",
    }
)

_TEMPORARY_STATE_PHRASES: tuple[str, ...] = (
    "hoje estou cansado",
    "hoje estou cansada",
    "agora estou com sono",
    "neste momento estou ocupado",
    "neste momento estou ocupada",
    "amanhã eu vejo isso",
    "amanha eu vejo isso",
)

_TECH_HINTS: frozenset[str] = frozenset(
    {
        "sqlite",
        "jarvis",
        "memory",
        "python",
        "docker",
        "kubernetes",
        "git",
        "api",
        "token",
        "feature",
        "function",
        "async",
        "database",
        "project",
        "save_memory",
        "jarvis_memory",
    }
)


_ws_re = re.compile(r"\s+")


def _collapse_spaces(text: str) -> str:
    return _ws_re.sub(" ", (text or "").strip())


def _normalize_record(category: str, key: str, value: str) -> str:
    cat = (category or "").strip().lower()
    k = (key or "").strip()
    v = _collapse_spaces(value or "")
    if k:
        return f"{cat}.{k}: {v}".strip()
    return f"{cat}: {v}".strip() if cat else v


def _is_low_signal_text(normalized_value: str) -> bool:
    t = normalized_value.strip().lower()
    if not t:
        return True
    if t in _LOW_SIGNAL_PHRASES:
        return True
    if len(t) < 4:
        return True
    return False


def _is_temporary_state(normalized_value: str) -> bool:
    low = normalized_value.casefold()
    for phrase in _TEMPORARY_STATE_PHRASES:
        if phrase.casefold() in low:
            return True
    return False


def _looks_technical(text: str) -> bool:
    low = text.casefold()
    if len(_collapse_spaces(text)) >= 40:
        return True
    for hint in _TECH_HINTS:
        if hint in low:
            return True
    return False


def decide_memory_save(
    *,
    category: str,
    key: str,
    value: str | None,
    project: str = "meu-jarvis",
) -> MemoryDecision:
    """Return a structured decision. Never writes storage or calls writer APIs."""
    raw = "" if value is None else str(value)
    stripped = raw.strip()
    collapsed_value = _collapse_spaces(raw)

    if not stripped:
        return MemoryDecision(
            should_save=False,
            reason="empty_content",
            memory_type=None,
            scope=None,
            project=None,
            requires_review=False,
            confidence=0.0,
            normalized_content="",
        )

    privacy = check_content_safe(collapsed_value)
    if not privacy.allowed:
        return MemoryDecision(
            should_save=False,
            reason="sensitive_content",
            memory_type=None,
            scope=None,
            project=None,
            requires_review=False,
            confidence=0.0,
            normalized_content="",
        )

    if _is_low_signal_text(collapsed_value):
        return MemoryDecision(
            should_save=False,
            reason="low_signal",
            memory_type=None,
            scope=None,
            project=None,
            requires_review=False,
            confidence=0.0,
            normalized_content=_normalize_record(category, key, collapsed_value),
        )

    if _is_temporary_state(collapsed_value):
        return MemoryDecision(
            should_save=False,
            reason="temporary_state",
            memory_type=None,
            scope=None,
            project=None,
            requires_review=False,
            confidence=0.0,
            normalized_content=_normalize_record(category, key, collapsed_value),
        )

    cat = (category or "").strip().lower()
    proj = (project or "").strip() or "meu-jarvis"
    scope_project = f"project:{proj}"
    normalized_full = _normalize_record(category, key, collapsed_value)

    if cat == "preferences":
        return MemoryDecision(
            should_save=True,
            reason="stable_preference",
            memory_type="PREFERENCE",
            scope="global",
            project=None,
            requires_review=False,
            confidence=0.85,
            normalized_content=normalized_full,
        )

    if cat == "projects":
        return MemoryDecision(
            should_save=True,
            reason="project_context",
            memory_type="PROJECT_CONTEXT",
            scope=scope_project,
            project=proj,
            requires_review=False,
            confidence=0.85,
            normalized_content=normalized_full,
        )

    if cat == "notes":
        use_technical = _looks_technical(collapsed_value)
        mtype = "TECHNICAL_STATE" if use_technical else "PROJECT_CONTEXT"
        conf = 0.82 if use_technical else 0.72
        return MemoryDecision(
            should_save=True,
            reason="technical_note",
            memory_type=mtype,
            scope=scope_project,
            project=proj,
            requires_review=not use_technical,
            confidence=conf,
            normalized_content=normalized_full,
        )

    if cat in {"identity", "relationships"}:
        return MemoryDecision(
            should_save=True,
            reason="personal_context_requires_review",
            memory_type="PREFERENCE",
            scope="global",
            project=None,
            requires_review=True,
            confidence=0.65,
            normalized_content=normalized_full,
        )

    if _looks_technical(collapsed_value):
        return MemoryDecision(
            should_save=True,
            reason="unknown_category_technical",
            memory_type="IDEA",
            scope=scope_project,
            project=proj,
            requires_review=True,
            confidence=0.58,
            normalized_content=normalized_full,
        )

    return MemoryDecision(
        should_save=False,
        reason="low_signal",
        memory_type=None,
        scope=None,
        project=None,
        requires_review=False,
        confidence=0.0,
        normalized_content=normalized_full,
    )
