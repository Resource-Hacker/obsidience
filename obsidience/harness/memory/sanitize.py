"""Bounded text sanitation at the historical memory boundary."""
import re

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_ -]?key|token|password|secret|credential)\b\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
)
def _redact(value: object, limit: int) -> str:
    text = str(value or "").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[: max(0, limit - 14)].rstrip() + "\n[truncated]"
    return text


