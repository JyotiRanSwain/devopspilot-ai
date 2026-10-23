"""Secret redaction applied to logs, metadata, incidents and reports."""
import re

MASK = "[REDACTED]"

_SENSITIVE_NAME = r"(?:pass(?:word|wd)?|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|credential|auth)"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), MASK),
    (re.compile(r"(?i)\b(authorization|proxy-authorization)\s*[:=]\s*(?:bearer|basic|token)?\s*[^\s,;\"']+(?:\s+[^\s,;\"']+)?"), r"\1: " + MASK),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + MASK),
    (re.compile(r"(?i)\b(set-cookie|cookie)\s*:\s*[^\r\n]+"), r"\1: " + MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), MASK),
    (re.compile(r"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}\b"), MASK),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), MASK),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), MASK),
    # scheme://user:password@host
    (re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(@)"), r"\1" + MASK + r"\2"),
    # key=value / key: value / "key": "value" where the key looks sensitive
    (re.compile(rf"(?i)(\"?[\w.-]*{_SENSITIVE_NAME}[\w.-]*\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)"), r"\1" + MASK),
]

_SENSITIVE_NAME_RE = re.compile(_SENSITIVE_NAME, re.I)


def redact(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def is_sensitive_name(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name))


def redact_env(env: list[str] | None) -> list[dict]:
    """Turn Docker 'KEY=value' env entries into safe {name, value} pairs.

    Values of sensitive-looking names are masked; other values are still scrubbed.
    """
    result = []
    for entry in env or []:
        name, _, value = entry.partition("=")
        result.append({"name": name, "value": MASK if is_sensitive_name(name) else redact(value)})
    return result
