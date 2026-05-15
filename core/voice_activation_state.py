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
    last_activation_at: float = 0.0
    activation_timeout_seconds: float = 10.0
    armed_buffer: tuple[str, ...] = ()
    first_buffer_time: float = 0.0
    buffer_timeout_seconds: float = 1.5
    local_ack_emitted_for_window: bool = False
    last_local_ack_text: str | None = None
    last_local_ack_at: float = 0.0
    last_local_ack_reason: str | None = None
    last_fragment_text: str | None = None
    last_fragment_at: float = 0.0


_LOCK = threading.Lock()
_STATE = VoiceActivationState()


def _now() -> float:
    return time.time()


def _normalize_text(text: str | None) -> str:
    return " ".join((text or "").split()).strip().lower()


def _is_near_duplicate_text(a: str | None, b: str | None) -> bool:
    left = _normalize_text(a)
    right = _normalize_text(b)
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) <= 4 or len(right) <= 4:
        return False
    from difflib import SequenceMatcher

    return SequenceMatcher(None, left, right).ratio() >= 0.92


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
        global _STATE
        timeout = max(0.1, float(timeout_seconds or 10.0))
        now = _now()
        current = _STATE
        state = VoiceActivationState(
            armed_until=now + timeout,
            matched_wake_word=(wake_word or "").strip().lower() or None,
            last_activation_text=activation_text,
            last_activation_at=now,
            activation_timeout_seconds=timeout,
            armed_buffer=(),
            first_buffer_time=0.0,
            buffer_timeout_seconds=1.5,
            local_ack_emitted_for_window=False,
            last_local_ack_text=current.last_local_ack_text,
            last_local_ack_at=current.last_local_ack_at,
            last_local_ack_reason=current.last_local_ack_reason,
            last_fragment_text=current.last_fragment_text,
            last_fragment_at=current.last_fragment_at,
        )
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
            _clear_armed_locked()
            return True
        if _STATE.armed_until and not _is_active_locked():
            _clear_armed_locked()
        return False


def clear_voice_activation() -> None:
    with _LOCK:
        _clear_locked()


def clear_armed_voice_activation() -> None:
    with _LOCK:
        _clear_armed_locked()


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


def can_emit_local_ack(*, now: float | None = None, cooldown_seconds: float = 2.0) -> bool:
    with _LOCK:
        current = _STATE
        current_now = now if now is not None else _now()
        if current.local_ack_emitted_for_window:
            return False
        if current.last_local_ack_at and current_now - current.last_local_ack_at < max(0.1, float(cooldown_seconds or 2.0)):
            return False
        return True


def record_local_ack(
    trigger_text: str,
    ack_text: str,
    *,
    reason: str = "local_ack",
    now: float | None = None,
) -> VoiceActivationState:
    with _LOCK:
        current = _STATE
        current_now = now if now is not None else _now()
        state = VoiceActivationState(
            armed_until=current.armed_until,
            matched_wake_word=current.matched_wake_word,
            last_activation_text=current.last_activation_text,
            last_activation_at=current.last_activation_at,
            activation_timeout_seconds=current.activation_timeout_seconds,
            armed_buffer=current.armed_buffer,
            first_buffer_time=current.first_buffer_time,
            buffer_timeout_seconds=current.buffer_timeout_seconds,
            local_ack_emitted_for_window=True,
            last_local_ack_text=_normalize_text(ack_text),
            last_local_ack_at=current_now,
            last_local_ack_reason=reason,
            last_fragment_text=_normalize_text(trigger_text) or current.last_fragment_text,
            last_fragment_at=current_now,
        )
        _set_locked(state)
        return state


def record_followup_fragment(fragment: str, *, now: float | None = None) -> tuple[str, ...]:
    cleaned = " ".join((fragment or "").split()).strip()
    if not cleaned:
        return get_followup_buffer()

    with _LOCK:
        current = _STATE
        current_now = now if now is not None else _now()
        timeout = current.buffer_timeout_seconds or 1.5
        if current.first_buffer_time and current.armed_buffer and current_now - current.first_buffer_time > timeout:
            _clear_followup_buffer_locked()
            current = _STATE
        buffer = current.armed_buffer + (cleaned,)
        _set_locked(
            VoiceActivationState(
                armed_until=current.armed_until,
                matched_wake_word=current.matched_wake_word,
                last_activation_text=current.last_activation_text,
                last_activation_at=current.last_activation_at,
                activation_timeout_seconds=current.activation_timeout_seconds,
                armed_buffer=buffer,
                first_buffer_time=current.first_buffer_time or current_now,
                buffer_timeout_seconds=timeout,
                local_ack_emitted_for_window=current.local_ack_emitted_for_window,
                last_local_ack_text=current.last_local_ack_text,
                last_local_ack_at=current.last_local_ack_at,
                last_local_ack_reason=current.last_local_ack_reason,
                last_fragment_text=_normalize_text(cleaned),
                last_fragment_at=current_now,
            )
        )
        return _STATE.armed_buffer


def is_duplicate_fragment(text: str, *, now: float | None = None, window_seconds: float = 2.0) -> bool:
    raw = _normalize_text(text)
    if not raw:
        return True

    with _LOCK:
        current = _STATE
        current_now = now if now is not None else _now()
        recent = max(0.1, float(window_seconds or 2.0))
        candidates = (
            (current.last_activation_text, current.last_activation_at),
            (current.last_fragment_text, current.last_fragment_at),
        )
        for candidate, at in candidates:
            if not candidate or not at:
                continue
            if current_now - at > recent:
                continue
            if _is_near_duplicate_text(raw, candidate):
                return True
        return False


def mark_fragment_from_text(text: str, *, now: float | None = None) -> VoiceActivationState:
    with _LOCK:
        current = _STATE
        current_now = now if now is not None else _now()
        state = VoiceActivationState(
            armed_until=current.armed_until,
            matched_wake_word=current.matched_wake_word,
            last_activation_text=current.last_activation_text,
            last_activation_at=current.last_activation_at,
            activation_timeout_seconds=current.activation_timeout_seconds,
            armed_buffer=current.armed_buffer,
            first_buffer_time=current.first_buffer_time,
            buffer_timeout_seconds=current.buffer_timeout_seconds,
            local_ack_emitted_for_window=current.local_ack_emitted_for_window,
            last_local_ack_text=current.last_local_ack_text,
            last_local_ack_at=current.last_local_ack_at,
            last_local_ack_reason=current.last_local_ack_reason,
            last_fragment_text=_normalize_text(text),
            last_fragment_at=current_now,
        )
        _set_locked(state)
        return state


def _clear_locked() -> None:
    global _STATE
    _STATE = VoiceActivationState()


def _clear_armed_locked() -> None:
    global _STATE
    _STATE = VoiceActivationState(
        armed_until=0.0,
        matched_wake_word=None,
        last_activation_text=_STATE.last_activation_text,
        last_activation_at=_STATE.last_activation_at,
        activation_timeout_seconds=_STATE.activation_timeout_seconds,
        armed_buffer=(),
        first_buffer_time=0.0,
        buffer_timeout_seconds=_STATE.buffer_timeout_seconds,
        local_ack_emitted_for_window=False,
        last_local_ack_text=_STATE.last_local_ack_text,
        last_local_ack_at=_STATE.last_local_ack_at,
        last_local_ack_reason=_STATE.last_local_ack_reason,
        last_fragment_text=_STATE.last_fragment_text,
        last_fragment_at=_STATE.last_fragment_at,
    )


def _clear_followup_buffer_locked() -> None:
    global _STATE
    _STATE = VoiceActivationState(
        armed_until=_STATE.armed_until,
        matched_wake_word=_STATE.matched_wake_word,
        last_activation_text=_STATE.last_activation_text,
        last_activation_at=_STATE.last_activation_at,
        activation_timeout_seconds=_STATE.activation_timeout_seconds,
        local_ack_emitted_for_window=_STATE.local_ack_emitted_for_window,
        last_local_ack_text=_STATE.last_local_ack_text,
        last_local_ack_at=_STATE.last_local_ack_at,
        last_local_ack_reason=_STATE.last_local_ack_reason,
        last_fragment_text=_STATE.last_fragment_text,
        last_fragment_at=_STATE.last_fragment_at,
    )


def _set_locked(state: VoiceActivationState) -> None:
    global _STATE
    _STATE = state
