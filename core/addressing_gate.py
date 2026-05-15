"""Wake word / addressing gate for microphone input."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable

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

_LEADING_FILLERS = {"oi", "ola", "olá", "hey", "ei", "ok", "okay", "por favor", "pf"}


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
