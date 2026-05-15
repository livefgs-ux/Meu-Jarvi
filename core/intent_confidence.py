"""Deterministic intent confidence checks for user text before tool execution."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from memory_engine.privacy_guard import check_content_safe

_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s?]+", re.UNICODE)

_SPEECH_INTERRUPT_PHRASES = (
    "para de falar",
    "pare de falar",
    "fica quieto",
    "cala a boca",
    "silencio",
    "silence",
    "stop",
    "halt",
    "shut up",
)
_SPEECH_SILENCE_PHRASES = (
    "fica quieto por um tempo",
    "modo silencio",
    "nao fale agora",
)
_SPEECH_RESUME_PHRASES = (
    "pode falar",
    "volta a falar",
    "resume",
    "pode responder normal",
)
_SPEECH_CONCISE_PHRASES = (
    "seja direto",
    "responde curto",
    "menos falacao",
    "fala menos",
    "resuma",
)
_SPEECH_NORMAL_PHRASES = (
    "pode explicar normal",
    "volta ao normal",
    "resposta normal",
)

_WEB_SEARCH_PHRASES = (
    "pesquisa",
    "pesquisar",
    "buscar",
    "procura",
    "procurar",
    "na internet",
    "na web",
    "internet",
    "web",
    "novidades",
    "noticia",
    "noticias",
    "preco",
    "precos",
    "preços",
    "comparar",
    "comparacao",
    "informacao atual",
    "informacoes atuais",
    "latest",
)
_OPEN_APP_PHRASES = (
    "abra ",
    "abrir ",
    "open ",
    "inicie ",
    "iniciar ",
    "launch ",
    "start ",
)
_BROWSER_PHRASES = (
    "navegador",
    "browser",
    "site",
    "pagina",
    "aba",
    "tab",
    "navegue",
    "clicar no navegador",
    "pesquisar no navegador",
)
_GAME_PHRASES = (
    "steam",
    "epic",
    "jogo",
    "game",
    "atualizar jogo",
    "baixar jogo",
    "instalar jogo",
    "listar jogos",
    "agendar atualizacao de jogo",
)
_FILE_PHRASES = (
    "arquivo",
    "ficheiro",
    "pasta",
    "folder",
    "documento",
    "criar",
    "deletar",
    "apagar",
    "mover",
    "copiar",
    "editar",
    "escrever",
    "ler",
)
_MEMORY_PHRASES = (
    "salve na memoria",
    "guarde na memoria",
    "anote na memoria",
    "grave na memoria",
    "remember that",
    "save to memory",
    "lembre que",
    "lembre-se que",
    "lembre se que",
    "memorize",
)
_CONTEXT_PHRASES = (
    "o que voce esta fazendo",
    "o que voce esta fazendo agora",
    "tem alguma task",
    "em andamento",
    "ultima busca",
    "qual foi a ultima busca",
    "o que voce buscou",
    "mostra essa busca",
    "mostra a busca",
    "qual alternativa",
    "abre essa alternativa",
    "por que falhou",
    "por que voce nao abriu",
    "status",
)
_GREETING_PHRASES = (
    "oi",
    "ola",
    "olá",
    "hello",
    "bom dia",
    "boa tarde",
    "boa noite",
)

_TOOL_THRESHOLDS = {
    "web_search": 0.55,
    "open_app": 0.60,
    "browser_control": 0.60,
    "game_update": 0.70,
    "file_operation": 0.65,
    "memory_save": 0.70,
    "speech_control": 0.55,
    "context_query": 0.45,
}


def _collapse_spaces(text: str) -> str:
    return _SPACE_RE.sub(" ", (text or "").strip())


def normalize_transcript(text: str) -> str:
    """Normalize a transcript for deterministic matching."""
    raw = _collapse_spaces(text)
    if not raw:
        return ""
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.lower()
    raw = _NON_WORD_RE.sub(" ", raw)
    return _collapse_spaces(raw)


def transcript_quality_score(text: str) -> float:
    """Score transcript quality in [0, 1]. Higher means clearer / less noisy."""
    norm = normalize_transcript(text)
    if not norm:
        return 0.0

    tokens = norm.split()
    if not tokens:
        return 0.0

    length = len(norm)
    uniq = len(set(tokens)) / len(tokens)
    alpha = sum(ch.isalpha() for ch in norm) / max(1, len(norm))
    avg_word_len = sum(len(t) for t in tokens) / len(tokens)
    punctuation_bonus = 0.08 if "?" in (text or "") or "!" in (text or "") else 0.0
    short_penalty = 0.0 if len(tokens) >= 4 else 0.18
    single_letter_penalty = 0.10 if any(len(t) == 1 for t in tokens) and len(tokens) > 2 else 0.0
    very_short_penalty = 0.15 if length < 12 else 0.0

    base = (
        min(1.0, length / 80.0) * 0.30
        + min(1.0, len(tokens) / 10.0) * 0.30
        + uniq * 0.15
        + min(1.0, avg_word_len / 9.0) * 0.15
        + alpha * 0.10
        + punctuation_bonus
    )
    base -= short_penalty + single_letter_penalty + very_short_penalty
    return max(0.0, min(1.0, base))


def _matches(text: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text)


def _intent_confidence(text: str, phrases: tuple[str, ...], base: float) -> float:
    matches = _matches(text, phrases)
    if not matches:
        return 0.0
    quality = transcript_quality_score(text)
    score = base + min(0.35, matches * 0.12) + quality * 0.35
    return max(0.0, min(1.0, score))


def classify_user_intent(text: str) -> dict[str, Any]:
    """Return a deterministic classification for the user transcript."""
    norm = normalize_transcript(text)
    quality = transcript_quality_score(text)
    if not norm:
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "reason": "empty_input",
            "clarification": "Não entendi com segurança. Pode repetir?",
            "normalized_text": "",
            "quality": quality,
        }

    if any(phrase in norm for phrase in _SPEECH_INTERRUPT_PHRASES):
        return {
            "intent": "speech_control",
            "confidence": _intent_confidence(norm, _SPEECH_INTERRUPT_PHRASES, 0.65),
            "reason": "speech_interrupt",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }
    if any(phrase in norm for phrase in _SPEECH_SILENCE_PHRASES):
        return {
            "intent": "speech_control",
            "confidence": _intent_confidence(norm, _SPEECH_SILENCE_PHRASES, 0.70),
            "reason": "speech_silence",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }
    if any(phrase in norm for phrase in _SPEECH_RESUME_PHRASES):
        return {
            "intent": "speech_control",
            "confidence": _intent_confidence(norm, _SPEECH_RESUME_PHRASES, 0.70),
            "reason": "speech_resume",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }
    if any(phrase in norm for phrase in _SPEECH_CONCISE_PHRASES):
        return {
            "intent": "speech_control",
            "confidence": _intent_confidence(norm, _SPEECH_CONCISE_PHRASES, 0.65),
            "reason": "speech_concise",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }
    if any(phrase in norm for phrase in _SPEECH_NORMAL_PHRASES):
        return {
            "intent": "speech_control",
            "confidence": _intent_confidence(norm, _SPEECH_NORMAL_PHRASES, 0.65),
            "reason": "speech_normal",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    if any(phrase in norm for phrase in _MEMORY_PHRASES):
        privacy = check_content_safe(text or "")
        confidence = _intent_confidence(norm, _MEMORY_PHRASES, 0.70)
        return {
            "intent": "memory_save",
            "confidence": confidence,
            "reason": "memory_save_safe" if privacy.allowed else "sensitive_memory",
            "clarification": None if privacy.allowed else "Conteúdo sensível detectado.",
            "normalized_text": norm if privacy.allowed else "",
            "quality": quality,
        }

    if any(phrase in norm for phrase in _FILE_PHRASES):
        return {
            "intent": "file_operation",
            "confidence": _intent_confidence(norm, _FILE_PHRASES, 0.55),
            "reason": "file_operation_request",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    if any(phrase in norm for phrase in _BROWSER_PHRASES):
        return {
            "intent": "browser_control",
            "confidence": _intent_confidence(norm, _BROWSER_PHRASES, 0.55),
            "reason": "browser_control_request",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    if any(phrase in norm for phrase in _OPEN_APP_PHRASES):
        return {
            "intent": "open_app",
            "confidence": _intent_confidence(norm, _OPEN_APP_PHRASES, 0.58),
            "reason": "open_app_request",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    if any(phrase in norm for phrase in _GAME_PHRASES):
        return {
            "intent": "game_update",
            "confidence": _intent_confidence(norm, _GAME_PHRASES, 0.60),
            "reason": "game_update_request",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    if any(phrase in norm for phrase in _WEB_SEARCH_PHRASES):
        return {
            "intent": "web_search",
            "confidence": _intent_confidence(norm, _WEB_SEARCH_PHRASES, 0.60),
            "reason": "web_search_request",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    question_like = (
        "?" in (text or "")
        and quality >= 0.55
        and any(marker in norm for marker in ("qual", "quais", "o que", "oque", "como", "why", "what", "how", "explain", "help"))
    )
    if question_like or any(phrase in norm for phrase in _CONTEXT_PHRASES):
        return {
            "intent": "context_query",
            "confidence": max(0.35, min(0.85, quality * 0.85 + 0.20)),
            "reason": "context_query_or_question",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    if any(phrase in norm for phrase in _GREETING_PHRASES):
        return {
            "intent": "context_query",
            "confidence": max(0.50, min(0.80, quality * 0.75 + 0.25)),
            "reason": "greeting",
            "clarification": None,
            "normalized_text": norm,
            "quality": quality,
        }

    return {
        "intent": "unknown",
        "confidence": max(0.05, min(0.45, quality * 0.35)),
        "reason": "uncertain_intent",
        "clarification": "Não entendi com segurança. Pode repetir?",
        "normalized_text": norm,
        "quality": quality,
    }


def _tool_intent_requirements(tool_name: str) -> tuple[str | None, float, str]:
    tool = (tool_name or "").strip().lower()
    if tool in {"web_search", "weather_report", "flight_finder", "youtube_video"}:
        return "web_search", _TOOL_THRESHOLDS["web_search"], "web_search"
    if tool == "open_app":
        return "open_app", _TOOL_THRESHOLDS["open_app"], "open_app"
    if tool == "browser_control":
        return "browser_control", _TOOL_THRESHOLDS["browser_control"], "browser_control"
    if tool == "game_updater":
        return "game_update", _TOOL_THRESHOLDS["game_update"], "game_update"
    if tool == "file_controller":
        return "file_operation", _TOOL_THRESHOLDS["file_operation"], "file_operation"
    if tool == "save_memory":
        return "memory_save", _TOOL_THRESHOLDS["memory_save"], "memory_save"
    if tool in {"computer_control", "computer_settings", "desktop_control", "send_message", "reminder", "code_helper", "dev_agent", "file_processor"}:
        return None, 0.0, "unmapped_tool"
    return None, 0.0, "unmapped_tool"


def _clarification_for_tool(tool_name: str, intent: str, reason: str) -> str:
    tool = (tool_name or "").strip().lower()
    if reason == "sensitive_memory":
        return "Não posso salvar conteúdo sensível. Pode repetir sem segredos?"
    if tool == "open_app":
        return "Não entendi qual app você quer abrir. Pode repetir de forma mais direta?"
    if tool == "browser_control":
        return "Não entendi qual ação no navegador você quer fazer. Pode repetir de forma mais direta?"
    if tool == "game_updater":
        return "Não entendi se você quer atualizar um jogo. Pode repetir de forma mais direta?"
    if tool == "file_controller":
        return "Não entendi qual arquivo ou pasta você quer manipular. Pode repetir de forma mais direta?"
    if tool == "save_memory":
        return "Não entendi se você quer salvar isso na memória. Pode repetir de forma mais direta?"
    if tool in {"web_search", "weather_report", "flight_finder", "youtube_video"}:
        return "Não entendi com segurança se você quer pesquisar. Pode repetir?"
    return "Não entendi com segurança. Pode repetir?"


def validate_tool_call_against_user_text(tool_name: str, args: dict | None, user_text: str | None) -> dict[str, Any]:
    """Validate a tool call against the latest user transcript."""
    if not user_text or not str(user_text).strip():
        return {
            "allow": True,
            "confidence": 0.0,
            "intent": "unknown",
            "reason": "no_user_text",
            "clarification": None,
        }

    analysis = classify_user_intent(user_text)
    expected_intent, threshold, mapped_reason = _tool_intent_requirements(tool_name)

    if expected_intent is None:
        if analysis["intent"] == "unknown" and analysis["confidence"] < 0.40:
            clarification = _clarification_for_tool(tool_name, analysis["intent"], analysis["reason"])
            return {
                "allow": False,
                "confidence": analysis["confidence"],
                "intent": analysis["intent"],
                "reason": f"low_confidence:{mapped_reason}",
                "clarification": clarification,
            }
        return {
            "allow": True,
            "confidence": analysis["confidence"],
            "intent": analysis["intent"],
            "reason": analysis["reason"],
            "clarification": None,
        }

    if analysis["reason"] == "sensitive_memory":
        clarification = _clarification_for_tool(tool_name, analysis["intent"], analysis["reason"])
        return {
            "allow": False,
            "confidence": analysis["confidence"],
            "intent": analysis["intent"],
            "reason": "sensitive_memory",
            "clarification": clarification,
        }

    if analysis["intent"] != expected_intent:
        clarification = _clarification_for_tool(tool_name, analysis["intent"], analysis["reason"])
        return {
            "allow": False,
            "confidence": analysis["confidence"],
            "intent": analysis["intent"],
            "reason": f"intent_mismatch:{analysis['intent']}!= {expected_intent}",
            "clarification": clarification,
        }

    if analysis["confidence"] < threshold:
        clarification = _clarification_for_tool(tool_name, analysis["intent"], analysis["reason"])
        return {
            "allow": False,
            "confidence": analysis["confidence"],
            "intent": analysis["intent"],
            "reason": f"low_confidence:{expected_intent}",
            "clarification": clarification,
        }

    if tool_name == "file_controller":
        action = str((args or {}).get("action", "")).strip().lower()
        if action in {"delete", "move", "rename", "write"} and analysis["confidence"] < 0.75:
            clarification = _clarification_for_tool(tool_name, analysis["intent"], analysis["reason"])
            return {
                "allow": False,
                "confidence": analysis["confidence"],
                "intent": analysis["intent"],
                "reason": "file_operation_needs_clear_evidence",
                "clarification": clarification,
            }

    if tool_name == "game_updater":
        if not any(marker in analysis["normalized_text"] for marker in ("steam", "epic", "jogo", "game")):
            clarification = _clarification_for_tool(tool_name, analysis["intent"], analysis["reason"])
            return {
                "allow": False,
                "confidence": analysis["confidence"],
                "intent": analysis["intent"],
                "reason": "missing_game_context",
                "clarification": clarification,
            }

    return {
        "allow": True,
        "confidence": analysis["confidence"],
        "intent": analysis["intent"],
        "reason": analysis["reason"],
        "clarification": None,
    }
