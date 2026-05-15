"""Wake word / addressing gate for microphone input."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
import unicodedata
from typing import Iterable

from core.voice_activation_state import (
    arm_voice_activation,
    clear_followup_buffer,
    clear_voice_activation,
    consume_voice_activation,
    flush_followup_buffer_if_ready,
    get_voice_activation_state,
    get_followup_buffer,
)

_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

DEFAULT_WAKE_WORDS = (
    "meu jarvis",
    "hey jarvis",
    "ei jarvis",
    "ok jarvis",
    "jarvis",
    "charles",
    "assistente",
)

_LEADING_FILLERS = {"oi", "ola", "hey", "ei", "ok", "okay", "por favor", "pf"}
_NOISE_PHRASES = {
    "sim",
    "online",
    "ok",
    "ah",
    "hum",
    "ta",
    "ne",
    "certo",
    "beleza",
    "oi",
    "estou",
    "esta",
    "to",
    "sou",
    "sao",
    "ta ouvindo",
    "estou ouvindo",
    "to ouvindo",
    "ouvindo",
    "consegue me ouvir",
    "me ouve",
    "me escuta",
    "tudo bem",
    "fala ai",
}
_NOISE_SINGLETONS = {
    "online",
    "sim",
    "ok",
    "ah",
    "hum",
    "ta",
    "ne",
    "certo",
    "beleza",
    "oi",
    "estou",
    "esta",
    "to",
    "sou",
    "sao",
}
_MEANINGFUL_SINGLE_TOKEN_COMMANDS = {"para", "stop", "cancela", "cancel", "pare"}
_MEANINGFUL_COMMAND_STARTS = {
    "abre",
    "abrir",
    "pesquisa",
    "pesquisar",
    "mostra",
    "mostrar",
    "fecha",
    "fechar",
    "cancela",
    "cancelar",
    "procura",
    "buscar",
}
_QUESTION_WORDS = {
    "quem",
    "qual",
    "quais",
    "quanto",
    "quantos",
    "quando",
    "onde",
    "como",
    "porque",
    "por",
}


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    stripped_text: str
    matched_wake_word: str | None


def _normalize_token(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.lower()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _strip_leading_noise_phrases(text: str) -> str:
    raw = normalize_address_text(text)
    if not raw:
        return ""

    phrases = sorted(_NOISE_PHRASES, key=lambda value: len(value.split()), reverse=True)
    changed = True
    while changed and raw:
        changed = False
        for phrase in phrases:
            if raw == phrase:
                return ""
            if raw.startswith(f"{phrase} "):
                raw = raw[len(phrase):].strip()
                changed = True
                break
    return raw


def normalize_address_text(text: str) -> str:
    tokens = [_normalize_token(tok) for tok in _tokens(text)]
    return _SPACE_RE.sub(" ", " ".join(tok for tok in tokens if tok).strip())


def _wake_word_phrases(wake_words: Iterable[str] | None = None) -> list[list[str]]:
    phrases = list(wake_words or DEFAULT_WAKE_WORDS)
    phrases.sort(key=lambda phrase: len(_normalize_token(phrase).split()), reverse=True)
    return [_normalize_token(phrase).split() for phrase in phrases if _normalize_token(phrase)]


def _match_wake_word_tokens(tokens: list[str], wake_words: Iterable[str] | None = None) -> tuple[str | None, int]:
    norm_tokens = [_normalize_token(tok) for tok in tokens]
    phrases = _wake_word_phrases(wake_words)

    for filler_count in range(0, min(2, len(norm_tokens)) + 1):
        if filler_count:
            leading = " ".join(norm_tokens[:filler_count]).strip()
            if leading not in _LEADING_FILLERS:
                continue

        start = filler_count
        for phrase_tokens in phrases:
            if not phrase_tokens:
                continue
            end = start + len(phrase_tokens)
            if norm_tokens[start:end] == phrase_tokens:
                matched = " ".join(phrase_tokens)
                return matched, end

    return None, 0


def is_addressed_to_jarvis(text: str, wake_words: list[str] | None = None) -> bool:
    tokens = _tokens(text)
    matched, _ = _match_wake_word_tokens(tokens, wake_words=wake_words)
    return matched is not None


def strip_wake_word(text: str, wake_words: list[str] | None = None) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""

    tokens = _tokens(raw)
    matched, consumed = _match_wake_word_tokens(tokens, wake_words=wake_words)
    if not matched:
        return raw

    stripped_tokens = tokens[consumed:]
    return " ".join(stripped_tokens).strip()


def is_meaningful_followup(text: str) -> bool:
    raw = _strip_leading_noise_phrases(text)
    if not raw:
        return False

    tokens = raw.split()
    if not tokens:
        return False

    if len(tokens) == 1:
        return tokens[0] in _MEANINGFUL_SINGLE_TOKEN_COMMANDS

    if tokens[0] in _MEANINGFUL_COMMAND_STARTS:
        return True

    if any(token in _QUESTION_WORDS for token in tokens):
        return True

    if "?" in (text or "") and len(tokens) >= 2:
        return True

    return False


def _is_noise_followup(text: str) -> bool:
    raw = _strip_leading_noise_phrases(text)
    if not raw:
        return True

    tokens = raw.split()
    if not tokens:
        return True

    return all(token in _NOISE_SINGLETONS for token in tokens)


def _is_bufferable_fragment(text: str) -> bool:
    raw = _strip_leading_noise_phrases(text)
    if not raw:
        return False

    tokens = raw.split()
    if not tokens:
        return False

    if is_meaningful_followup(raw):
        return False

    if _is_noise_followup(raw):
        return False

    return len(tokens) <= 2


def should_process_user_utterance(
    text: str,
    mic_mode: bool = True,
    text_input_always_allowed: bool = True,
) -> GateDecision:
    raw = (text or "").strip()
    if not raw:
        return GateDecision(False, "empty_text", "", None)

    if not mic_mode and text_input_always_allowed:
        return GateDecision(True, "text_input_allowed", raw, None)

    if not mic_mode:
        return GateDecision(True, "text_input_allowed", raw, None)

    matched = None
    try:
        matched, _ = _match_wake_word_tokens(_tokens(raw))
    except Exception as exc:  # fail closed for audio
        return GateDecision(False, f"gate_error:{exc}", "", None)

    if not matched:
        return GateDecision(False, "not_addressed", "", None)

    return GateDecision(True, "wake_word_matched", strip_wake_word(raw), matched)


def should_process_audio_utterance(
    text: str,
    wake_words: list[str] | None = None,
    timeout_seconds: float = 10.0,
) -> GateDecision:
    raw = (text or "").strip()
    if not raw:
        return GateDecision(False, "empty_text", "", None)

    try:
        tokens = _tokens(raw)
        matched, _ = _match_wake_word_tokens(tokens, wake_words=wake_words)
    except Exception as exc:  # fail closed for audio
        return GateDecision(False, f"gate_error:{exc}", "", None)

    if matched:
        stripped = strip_wake_word(raw, wake_words=wake_words)
        clear_voice_activation()
        clear_followup_buffer()
        if not stripped:
            arm_voice_activation(matched, timeout_seconds=timeout_seconds, activation_text=raw)
            return GateDecision(True, "wake_word_only", "", matched)
        return GateDecision(True, "wake_word_matched", stripped, matched)

    state = get_voice_activation_state()
    if state.armed_until:
        now = time.time()
        if state.armed_until <= now:
            clear_voice_activation()
            clear_followup_buffer()
            return GateDecision(False, "armed_expired", "", state.matched_wake_word)
        buffered = " ".join(get_followup_buffer()).strip()
        candidate = " ".join(part for part in [buffered, raw] if part).strip()
        if candidate and is_meaningful_followup(candidate):
            if consume_voice_activation():
                clear_followup_buffer()
                return GateDecision(True, "armed_followup", candidate, state.matched_wake_word)
        if _is_bufferable_fragment(raw):
            return GateDecision(False, "armed_fragment", raw, state.matched_wake_word)
        if candidate and _is_bufferable_fragment(candidate):
            return GateDecision(False, "armed_fragment", candidate, state.matched_wake_word)
        if buffered:
            flush_followup_buffer_if_ready(now=now)
        return GateDecision(False, "armed_non_meaningful", "", state.matched_wake_word)

    return GateDecision(False, "not_addressed", "", None)
