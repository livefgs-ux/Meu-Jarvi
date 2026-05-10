"""Rule-based request context detection for the standalone brain foundation."""

from __future__ import annotations

from collections.abc import Iterable


KEYWORDS = {
    "debugging": {
        "error",
        "errors",
        "traceback",
        "fail",
        "failed",
        "exception",
        "modulenotfounderror",
        "bug",
        "debug",
        "broken",
        "crash",
    },
    "sysadmin": {
        "cmd",
        "powershell",
        "python",
        "pip",
        "venv",
        "path",
        "git",
        "windows",
        "linux",
        "terminal",
        "shell",
    },
    "security": {
        "secret",
        "token",
        "api key",
        "apikey",
        "password",
        "permission",
        "delete",
        "remove",
        "credential",
        "private key",
    },
    "architecture": {
        "architecture",
        "structure",
        "design",
        "roadmap",
        "plan",
        "planning",
    },
    "memory": {
        "memory",
        "remember",
        "learn",
        "brain",
        "global rule",
        "project context",
        "memoria",
    },
    "code_review": {
        "review",
        "audit",
        "code quality",
        "regression",
        "risks",
    },
    "execution": {
        "run",
        "execute",
        "apply",
        "patch",
        "modify",
        "change",
        "edit",
    },
    "teaching": {
        "explain",
        "teach",
        "understand",
        "why",
        "how",
        "porque",
    },
    "creative": {
        "music",
        "video",
        "thumbnail",
        "lyrics",
        "prompt image",
        "image prompt",
        "creative",
    },
}

TASK_PRIORITY = [
    "security",
    "memory",
    "debugging",
    "sysadmin",
    "architecture",
    "code_review",
    "execution",
    "teaching",
    "creative",
]

MODE_BY_TASK = {
    "debugging": "Debugger",
    "sysadmin": "Sysadmin",
    "security": "Security Reviewer",
    "architecture": "Architect",
    "memory": "Memory Engineer",
    "code_review": "Code Reviewer",
    "execution": "Executor",
    "teaching": "Teacher",
    "creative": "Creative Director",
    "general": "General Assistant",
}


def _find_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    found = []
    for keyword in keywords:
        if keyword in text:
            found.append(keyword)
    return sorted(found)


def detect_context(user_input: str, project: str | None = None) -> dict:
    raw = user_input or ""
    text = raw.lower()

    detected: dict[str, list[str]] = {}
    flat_keywords: list[str] = []
    for task, keywords in KEYWORDS.items():
        matches = _find_keywords(text, keywords)
        if matches:
            detected[task] = matches
            flat_keywords.extend(matches)

    task_type = "general"
    for candidate in TASK_PRIORITY:
        if candidate in detected:
            task_type = candidate
            break

    risk_level = "low"
    if "security" in detected:
        risk_level = "high"
    elif task_type in {"execution", "sysadmin"} or {"delete", "remove", "permission"} & set(flat_keywords):
        risk_level = "medium"

    needs_execution = task_type in {"execution", "sysadmin"} or any(
        word in text for word in ("run", "execute", "apply", "patch", "modify", "delete", "remove")
    )
    needs_memory = task_type == "memory" or any(
        phrase in text for phrase in ("remember", "learn", "global rule", "project context")
    )

    probable_project = project
    if probable_project is None and "meu jarvi" in text:
        probable_project = "Meu-Jarvi"

    recommended_mode = MODE_BY_TASK.get(task_type, "General Assistant")

    return {
        "raw_input": raw,
        "probable_project": probable_project,
        "task_type": task_type,
        "risk_level": risk_level,
        "needs_memory": needs_memory,
        "needs_execution": needs_execution,
        "detected_keywords": sorted(set(flat_keywords)),
        "keyword_groups": detected,
        "recommended_mode": recommended_mode,
    }
