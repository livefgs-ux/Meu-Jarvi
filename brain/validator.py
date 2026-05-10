"""Validation helpers for the standalone brain foundation."""

from __future__ import annotations

from .context_detector import detect_context
from .router import choose_mode
from memory_engine.schemas import (
    normalize_memory_type,
    validate_content,
    validate_memory_scope_policy,
    validate_scope,
)


def validate_memory_request(memory_type: str, scope: str, content: str) -> None:
    normalized_type = normalize_memory_type(memory_type)
    normalized_scope = validate_scope(scope)
    validate_content(content)
    validate_memory_scope_policy(normalized_type, normalized_scope)


def validate_brain_request(user_input: str, project: str | None = None) -> dict:
    context = detect_context(user_input, project=project)
    mode = choose_mode(context)

    keywords = set(context.get("detected_keywords", []))
    unsafe_execution = bool(
        context.get("needs_execution")
        and (
            context.get("risk_level") == "high"
            or keywords & {"delete", "secret", "token", "api key", "password", "credential", "private key"}
        )
    )

    memory_scope_risk = False
    missing_project_context = False
    raw = context.get("raw_input", "").lower()
    if context.get("needs_memory"):
        mentions_project_context = "project context" in raw or "technical state" in raw
        mentions_global = "global" in raw or "global rule" in raw
        memory_scope_risk = mentions_project_context and mentions_global
        missing_project_context = mentions_project_context and not context.get("probable_project")

    return {
        "context": context,
        "mode": mode,
        "unsafe_execution": unsafe_execution,
        "memory_scope_risk": memory_scope_risk,
        "missing_project_context": missing_project_context,
        "allowed_to_execute": False,
        "notes": [
            "Standalone brain validation only; no shell execution is performed.",
        ],
    }
