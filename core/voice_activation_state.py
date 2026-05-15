"""Mutable wake-word activation state for microphone follow-up turns."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class VoiceActivationState:
    armed_until: float = 0.0
    matched_wake_word: str | None = None
    last_activation_text: str | None = None
    activation_timeout_seconds: float = 10.0


_LOCK = threading.Lock()
_STATE = VoiceActivationState()


def _now() -> float:
    return time.time()


def _is_active_locked(now: float | None = None) -> bool:
    current = now if now is not None else _now()
    return _STATE.armed_until > current


def get_voice_activation_state() -> VoiceActivationState:
    with _LOCK:
        return _STATE


def arm_voice_activation(
    wake_word: str,
    timeout_seconds: float = 10.0,
    activation_text: str | None = None,
) -> VoiceActivationState:
    with _LOCK:
        timeout = max(0.1, float(timeout_seconds or 10.0))
        now = _now()
        state = VoiceActivationState(
            armed_until=now + timeout,
            matched_wake_word=(wake_word or "").strip().lower() or None,
            last_activation_text=activation_text,
            activation_timeout_seconds=timeout,
        )
        global _STATE
        _STATE = state
        return state


def is_voice_activation_active() -> bool:
    with _LOCK:
        if _STATE.armed_until and not _is_active_locked():
            _clear_locked()
            return False
        return _is_active_locked()


def consume_voice_activation() -> bool:
    with _LOCK:
        if _STATE.armed_until and _is_active_locked():
            _clear_locked()
            return True
        if _STATE.armed_until and not _is_active_locked():
            _clear_locked()
        return False


def clear_voice_activation() -> None:
    with _LOCK:
        _clear_locked()


def _clear_locked() -> None:
    global _STATE
    _STATE = VoiceActivationState()
