"""Standalone Jarvis Brain foundation.

The brain package is intentionally isolated from the running Jarvis app. It
does not import UI modules, call Gemini, execute shell commands, or connect to
the current runtime.
"""

from .context_detector import detect_context
from .master_agent import JarvisBrain
from .router import choose_mode
from .validator import validate_brain_request, validate_memory_request

__all__ = [
    "JarvisBrain",
    "choose_mode",
    "detect_context",
    "validate_brain_request",
    "validate_memory_request",
]
