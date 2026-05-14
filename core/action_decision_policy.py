"""Deterministic intent/risk classification before any local action or tool execution.

Phase 5A: pure policy — no process-spawning APIs, no actions/, no file I/O, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from memory_engine.privacy_guard import check_content_safe

INTENTS = frozenset(
    {
        "chat",
        "memory_save",
        "local_action",
        "file_read",
        "file_write",
        "file_delete",
        "system_command",
        "unknown",
    }
)
RISKS = frozenset({"low", "medium", "high"})
ACTIONS = frozenset({"allow", "confirm", "deny", "answer_only"})

_ws_re = re.compile(r"\s+")


def _collapse_spaces(text: str) -> str:
    return _ws_re.sub(" ", (text or "").strip())


_MEMORY_PHRASES: tuple[str, ...] = (
    "salve na memória",
    "salve na memoria",
    "guarde na memória",
    "guarde na memoria",
    "anote na memória",
    "anote na memoria",
    "grave na memória",
    "grave na memoria",
    "save to memory",
    "remember that",
    "memorize que",
    "memorize ",
    "lembre que",
    "lembre-se que",
    "lembre se que",
)

_MEMORY_PASSWORD_HINT = re.compile(
    r"\b(salve|guarde|lembre|memorize|remember)\b.*\b(senha|password)\b|\b(senha|password)\b.*\b(salve|guarde|lembre|memorize|remember)\b",
    re.IGNORECASE,
)


def _is_memory_intent(low: str) -> bool:
    if any(p in low for p in _MEMORY_PHRASES):
        return True
    if low.startswith("salve ") and ("memória" in low or "memoria" in low or "memory" in low):
        return True
    if _MEMORY_PASSWORD_HINT.search(low):
        return True
    if ("api" in low and "key" in low) and any(w in low for w in ("salve", "guarde", "lembre", "memorize", "remember")):
        return True
    return False


_FILE_DELETE_PATTERNS: tuple[str, ...] = (
    "delete o arquivo",
    "delete o ficheiro",
    "delete the file",
    "delete the folder",
    "apague o arquivo",
    "apague o ficheiro",
    "apague a pasta",
    "apague todos",
    "remova todos",
    "remova os arquivos",
    "remova os ficheiros",
    "remove all files",
    "remove all the files",
    "remova todos os arquivos",
    "remova todos os ficheiros",
    "exclua o arquivo",
    "exclua a pasta",
)

_DESTRUCTIVE_SYSTEM: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "rm -r -f",
    "del /s",
    "del /q",
    "rmdir /s",
    "format c:",
    "format c\\",
    "format drive",
    "mkfs",
    "dd if=",
    ":(){ :|:& };:",
    "shutdown /s",
    "shutdown -s",
    "reg delete",
    "reg add",
    "registry edit",
    "editar o registro",
    "edite o registro",
)


def _is_file_delete(low: str) -> bool:
    return any(p in low for p in _FILE_DELETE_PATTERNS)


def _is_destructive_system(low: str) -> bool:
    return any(p in low for p in _DESTRUCTIVE_SYSTEM)


_SYSTEM_TRIGGERS: tuple[str, ...] = (
    "rode powershell",
    "rode o powershell",
    "execute powershell",
    "run powershell",
    "rode cmd",
    "execute cmd",
    "rode pip",
    "execute pip",
    "pip install",
    "rode npm",
    "execute npm",
    "npm install",
    "execute git",
    "rode git",
    "git push",
    "git pull",
    "execute bash",
    "rode bash",
    "execute shell",
    "run terminal",
    "abra o terminal",
)


def _is_system_command(low: str) -> bool:
    if "execute " in low or low.startswith("execute ") or "rode " in low or low.startswith("rode "):
        return True
    if low.startswith("run ") or " run " in low:
        return True
    if any(t in low for t in _SYSTEM_TRIGGERS):
        return True
    return False


_FILE_WRITE_PATTERNS: tuple[str, ...] = (
    "crie um arquivo",
    "crie um ficheiro",
    "create a file",
    "create file",
    "edite o arquivo",
    "edite o ficheiro",
    "edit file",
    "edit the file",
    "salve isso em",
    "save this to",
    "save to file",
)

_FILE_READ_PATTERNS: tuple[str, ...] = (
    "leia o arquivo",
    "leia o ficheiro",
    "read file",
    "read the file",
    "mostre o conteúdo",
    "mostre o conteudo",
    "abra o arquivo",
    "abra o ficheiro",
    "open the file",
)


def _is_file_write(low: str) -> bool:
    return any(p in low for p in _FILE_WRITE_PATTERNS)


def _is_file_read(low: str) -> bool:
    return any(p in low for p in _FILE_READ_PATTERNS)


_LOCAL_ACTION_PATTERNS: tuple[str, ...] = (
    "abra o ",
    "abra a ",
    "abrir o ",
    "abrir a ",
    "open ",
    "feche o ",
    "feche a ",
    "tire um print",
    "tirar print",
    "tire print",
    "screenshot",
    "captura de tela",
    "captura de ecrã",
    "print da tela",
)


def _is_local_action(low: str) -> bool:
    return any(p in low for p in _LOCAL_ACTION_PATTERNS)


_CHAT_STARTERS: tuple[str, ...] = (
    "qual é",
    "qual e ",
    "quais são",
    "quais sao",
    "o que é",
    "o que e ",
    "oque é",
    "explique ",
    "me explica",
    "me ajude",
    "como funciona",
    "por que ",
    "porque ",
    "what is ",
    "what are ",
    "how does ",
    "explain ",
    "help me understand",
    "help me to understand",
)


def _is_chat(low: str, raw_collapsed: str) -> bool:
    if "?" in raw_collapsed and len(raw_collapsed) > 8:
        if not _is_memory_intent(low):
            return True
    if any(low.startswith(s) or f" {s}" in low for s in _CHAT_STARTERS):
        return True
    return False


@dataclass(frozen=True, slots=True)
class ActionDecision:
    intent: str
    risk: str
    action: str
    reason: str
    requires_confirmation: bool
    normalized_text: str


def decide_action_request(text: str) -> ActionDecision:
    """Classify user text. Does not execute tools, actions, or filesystem operations."""
    collapsed = _collapse_spaces(text or "")
    if not collapsed:
        return ActionDecision(
            intent="unknown",
            risk="low",
            action="answer_only",
            reason="empty_input",
            requires_confirmation=False,
            normalized_text="",
        )

    low = collapsed.lower()

    if _is_file_delete(low):
        return ActionDecision(
            intent="file_delete",
            risk="high",
            action="deny",
            reason="file_delete_policy",
            requires_confirmation=True,
            normalized_text=low,
        )

    if _is_destructive_system(low):
        return ActionDecision(
            intent="system_command",
            risk="high",
            action="deny",
            reason="destructive_system_command",
            requires_confirmation=False,
            normalized_text=low,
        )

    if _is_system_command(low):
        return ActionDecision(
            intent="system_command",
            risk="high",
            action="confirm",
            reason="system_command_review",
            requires_confirmation=True,
            normalized_text=low,
        )

    if _is_file_write(low):
        return ActionDecision(
            intent="file_write",
            risk="medium",
            action="confirm",
            reason="file_write_review",
            requires_confirmation=True,
            normalized_text=low,
        )

    if _is_file_read(low):
        return ActionDecision(
            intent="file_read",
            risk="medium",
            action="confirm",
            reason="file_read_review",
            requires_confirmation=True,
            normalized_text=low,
        )

    if _is_local_action(low):
        return ActionDecision(
            intent="local_action",
            risk="medium",
            action="confirm",
            reason="local_action_review",
            requires_confirmation=True,
            normalized_text=low,
        )

    if _is_memory_intent(low):
        pr = check_content_safe(collapsed)
        if not pr.allowed:
            return ActionDecision(
                intent="memory_save",
                risk="high",
                action="deny",
                reason="sensitive_memory",
                requires_confirmation=False,
                normalized_text="",
            )
        return ActionDecision(
            intent="memory_save",
            risk="low",
            action="allow",
            reason="memory_save_ok",
            requires_confirmation=False,
            normalized_text=low,
        )

    if _is_chat(low, collapsed):
        return ActionDecision(
            intent="chat",
            risk="low",
            action="answer_only",
            reason="chat_question",
            requires_confirmation=False,
            normalized_text=low,
        )

    return ActionDecision(
        intent="unknown",
        risk="medium",
        action="confirm",
        reason="uncertain_intent",
        requires_confirmation=True,
        normalized_text=low,
    )
