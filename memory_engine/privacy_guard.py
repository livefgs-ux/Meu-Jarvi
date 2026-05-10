"""Privacy checks for memory writes."""

from __future__ import annotations

import re
from dataclasses import dataclass


SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*TOKEN[A-Za-z0-9_]*\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*KEY[A-Za-z0-9_]*\s*=\s*\S+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?m)^\s*[A-Z0-9_]{3,}\s*=\s*['\"]?[^'\"\s]{12,}['\"]?\s*$"),
]


@dataclass(frozen=True, slots=True)
class PrivacyResult:
    allowed: bool
    reason: str = ""


def check_content_safe(content: str) -> PrivacyResult:
    text = content or ""
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return PrivacyResult(False, "Content appears to contain a secret or credential")
    return PrivacyResult(True, "")


def assert_content_safe(content: str) -> None:
    result = check_content_safe(content)
    if not result.allowed:
        raise ValueError(result.reason)
