"""JSON logging with conservative redaction.

Logs carry internal IDs, stage names, statuses and timings. They must not carry names,
contacts, addresses, clinical text, message bodies, tokens or credentials. Redaction is
a safety net, not permission to log content.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = {
    "name",
    "full_name",
    "display_name",
    "patient_name",
    "phone",
    "mobile",
    "email",
    "address",
    "abha",
    "aadhaar",
    "mrn",
    "message",
    "content",
    "prompt",
    "answer",
    "transcript",
    "clinical_text",
    "note_text",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "api_key",
    "cookie",
    "set-cookie",
}
_REDACTED = "[redacted]"
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{12,16}(?!\d)")


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        value = _EMAIL.sub(_REDACTED, value)
        value = _PHONE.sub(_REDACTED, value)
        return _LONG_NUMBER.sub(_REDACTED, value)
    if isinstance(value, dict):
        return {
            key: (_REDACTED if str(key).lower() in SENSITIVE_KEYS else _redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in (
            "trace_id",
            "span_id",
            "request_id",
            "actor_subject",
            "actor_role",
            "session_id",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            if str(key).lower() in SENSITIVE_KEYS:
                payload[key] = _REDACTED
            else:
                payload[key] = _redact_value(value)
        return json.dumps(_redact_value(payload), ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
