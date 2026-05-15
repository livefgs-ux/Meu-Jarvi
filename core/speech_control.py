"""Local speech interruption and silence control helpers."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
import re
import unicodedata
from typing import Any


class SpeechCommandType(str, Enum):
    NONE = "none"
    INTERRUPT_SPEECH = "interrupt_speech"
    TEMPORARY_SILENCE = "temporary_silence"
    RESUME_SPEECH = "resume_speech"
    CANCEL_TASK = "cancel_task"
    CONCISE_MODE = "concise_mode"
    NORMAL_MODE = "normal_mode"


@dataclass
class SpeechControlState:
    is_silenced: bool = False
    concise_mode: bool = False
    interrupted_at: float | None = None
    silence_until: float | None = None
    last_command: str = SpeechCommandType.NONE.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_text(text: str) -> str:
    raw = unicodedata.normalize("NFKD", text or "")
    ascii_text = raw.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"\s+", " ", ascii_text)
    return ascii_text.strip().lower()


def _match_any(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        if re.search(pattern, text):
            return pattern
    return ""


_COMMAND_PATTERNS: list[tuple[SpeechCommandType, list[str]]] = [
    (
        SpeechCommandType.CANCEL_TASK,
        [
            r"\bcancela essa tarefa\b",
            r"\bcancela a busca\b",
            r"\bpara essa tarefa\b",
            r"\bnao faz mais isso\b",
            r"\bcancel this task\b",
            r"\bcancel the task\b",
        ],
    ),
    (
        SpeechCommandType.TEMPORARY_SILENCE,
        [
            r"\bfica quieto por um tempo\b",
            r"\bmodo silencio\b",
            r"\bnao fale agora\b",
        ],
    ),
    (
        SpeechCommandType.RESUME_SPEECH,
        [
            r"\bpode falar\b",
            r"\bvolta a falar\b",
            r"\bresume\b",
            r"\bpode responder normal\b",
            r"\bresume speaking\b",
        ],
    ),
    (
        SpeechCommandType.CONCISE_MODE,
        [
            r"\bseja direto\b",
            r"\bresponde curto\b",
            r"\bmenos falacao\b",
            r"\bfala menos\b",
            r"\bresuma\b",
            r"\bbe concise\b",
            r"\bshort answer\b",
        ],
    ),
    (
        SpeechCommandType.NORMAL_MODE,
        [
            r"\bpode explicar normal\b",
            r"\bvolta ao normal\b",
            r"\bresposta normal\b",
            r"\bnormal mode\b",
        ],
    ),
    (
        SpeechCommandType.INTERRUPT_SPEECH,
        [
            r"^\s*para\s*$",
            r"^\s*pare\s*$",
            r"^\s*stop\s*$",
            r"\bquieto\b",
            r"\bfica quieto\b",
            r"\bcala\b",
            r"\bcala a boca\b",
            r"\bsilencio\b",
            r"\bsilence\b",
            r"\bhalt\b",
            r"\bshut up\b",
            r"\bpara de falar\b",
            r"\bpare de falar\b",
            r"\bstop talking\b",
            r"\bstop speaking\b",
        ],
    ),
]


def detect_speech_control_command(text: str) -> dict[str, Any]:
    normalized = _normalize_text(text)
    if not normalized:
        return {
            "command_type": SpeechCommandType.NONE.value,
            "matched_phrase": "",
            "raw_text": text or "",
            "normalized_text": normalized,
        }

    for command_type, patterns in _COMMAND_PATTERNS:
        matched = _match_any(normalized, patterns)
        if matched:
            return {
                "command_type": command_type.value,
                "matched_phrase": matched,
                "raw_text": text or "",
                "normalized_text": normalized,
            }

    return {
        "command_type": SpeechCommandType.NONE.value,
        "matched_phrase": "",
        "raw_text": text or "",
        "normalized_text": normalized,
    }


def speech_command_is_active(result: dict[str, Any]) -> bool:
    return result.get("command_type") not in {SpeechCommandType.NONE.value, "", None}
