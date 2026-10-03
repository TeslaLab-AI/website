"""Mask secrets in log output.

Call install_log_masking() once at app startup (before or after logging
config; it wraps the log record factory, so every handler is covered).
It masks the message, its %-args, and exception tracebacks.
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Callable

REDACTED = "***REDACTED***"

# Specific, high-confidence patterns first.
_TOKEN_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
]

# "Authorization: Bearer xxx" / "Basic xxx" / "token xxx"
_AUTH_HEADER = re.compile(
    r"(?i)(authorization\s*[:=]\s*)((?:bearer|basic|token)\s+)?[^\s,'\"]+"
)

# https://user:password@host
_URL_CREDS = re.compile(r"(https?://[^/\s:@]+:)[^@\s/]+(@)")

# name=value / name: value where the name looks sensitive
_KEY_VALUE = re.compile(
    r"(?i)\b([\w-]*(?:token|secret|password|passwd|api[_-]?key)[\w-]*)"
    r"(\s*[=:]\s*)(['\"]?)(?!\*\*\*REDACTED)[^\s'\",;]+"
)


def mask_secrets(text: str) -> str:
    if not text:
        return text
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _AUTH_HEADER.sub(lambda m: f"{m.group(1)}{m.group(2) or ''}{REDACTED}", text)
    text = _URL_CREDS.sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(2)}", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}", text)
    return text


class SecretMaskingFilter(logging.Filter):
    """Attach to a handler if you prefer filters over the record factory."""

    def filter(self, record: logging.LogRecord) -> bool:
        _mask_record(record)
        return True


def _mask_record(record: logging.LogRecord) -> None:
    try:
        message = record.getMessage()
    except Exception:  # bad format args; fall back to the raw message
        message = str(record.msg)
    record.msg = mask_secrets(message)
    record.args = None
    if record.exc_info and not record.exc_text:
        record.exc_text = mask_secrets("".join(traceback.format_exception(*record.exc_info)).rstrip())
    elif record.exc_text:
        record.exc_text = mask_secrets(record.exc_text)


def install_log_masking() -> Callable[[], None]:
    """Mask secrets on every log record. Returns a function that undoes it."""
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        _mask_record(record)
        return record

    logging.setLogRecordFactory(factory)

    def uninstall() -> None:
        logging.setLogRecordFactory(previous)

    return uninstall