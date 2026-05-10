"""Rule-based operating mode router for the standalone brain foundation."""

from __future__ import annotations


MODES = {
    "Architect",
    "Debugger",
    "Security Reviewer",
    "Sysadmin",
    "Code Reviewer",
    "Memory Engineer",
    "Executor",
    "Teacher",
    "Creative Director",
    "General Assistant",
}


def choose_mode(context: dict) -> str:
    task_type = (context or {}).get("task_type", "general")
    risk_level = (context or {}).get("risk_level", "low")
    needs_execution = bool((context or {}).get("needs_execution"))
    keywords = set((context or {}).get("detected_keywords", []))

    if risk_level == "high" and (
        needs_execution
        or task_type in {"security", "execution"}
        or keywords & {"delete", "secret", "token", "api key", "password", "credential"}
    ):
        return "Security Reviewer"

    if task_type == "memory":
        return "Memory Engineer"
    if task_type == "debugging":
        return "Debugger"
    if task_type == "sysadmin":
        return "Sysadmin"
    if task_type == "architecture":
        return "Architect"
    if task_type == "code_review":
        return "Code Reviewer"
    if task_type == "execution":
        return "Executor"
    if task_type == "teaching":
        return "Teacher"
    if task_type == "creative":
        return "Creative Director"
    return "General Assistant"
