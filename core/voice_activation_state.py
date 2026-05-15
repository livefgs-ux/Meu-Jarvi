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
    armed_buffer: tuple[str, ...] = ()
    first_buffer_time: float = 0.0
    buffer_timeout_seconds: float = 1.5


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
            armed_buffer=(),
            first_buffer_time=0.0,
            buffer_timeout_seconds=1.5,
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


def get_followup_buffer() -> tuple[str, ...]:
    with _LOCK:
        return _STATE.armed_buffer


def append_followup_fragment(fragment: str, buffer_timeout_seconds: float = 1.5) -> tuple[str, ...]:
    cleaned = " ".join((fragment or "").split()).strip()
    if not cleaned:
        return get_followup_buffer()

    with _LOCK:
        current = _STATE
        now = _now()
        timeout = max(0.1, float(buffer_timeout_seconds or 1.5))
        if current.first_buffer_time and current.armed_buffer and now - current.first_buffer_time > current.buffer_timeout_seconds:
            _clear_followup_buffer_locked()
            current = _STATE
        buffer = current.armed_buffer + (cleaned,)
        _set_locked(
            VoiceActivationState(
                armed_until=current.armed_until,
                matched_wake_word=current.matched_wake_word,
                last_activation_text=current.last_activation_text,
                activation_timeout_seconds=current.activation_timeout_seconds,
                armed_buffer=buffer,
                first_buffer_time=current.first_buffer_time or now,
                buffer_timeout_seconds=timeout,
            )
        )
        return _STATE.armed_buffer


def flush_followup_buffer_if_ready(now: float | None = None) -> str:
    with _LOCK:
        current = _STATE
        if not current.armed_buffer:
            return ""
        current_now = now if now is not None else _now()
        if current.first_buffer_time and current_now - current.first_buffer_time >= current.buffer_timeout_seconds:
            text = " ".join(current.armed_buffer).strip()
            _clear_followup_buffer_locked()
            return text
        return ""


def clear_followup_buffer() -> None:
    with _LOCK:
        _clear_followup_buffer_locked()


def _clear_locked() -> None:
    global _STATE
    _STATE = VoiceActivationState()


def _clear_followup_buffer_locked() -> None:
    global _STATE
    _STATE = VoiceActivationState(
        armed_until=_STATE.armed_until,
        matched_wake_word=_STATE.matched_wake_word,
        last_activation_text=_STATE.last_activation_text,
        activation_timeout_seconds=_STATE.activation_timeout_seconds,
    )


def _set_locked(state: VoiceActivationState) -> None:
    global _STATE
    _STATE = state
