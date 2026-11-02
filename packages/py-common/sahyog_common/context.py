"""Server-minted execution context for tool calls.

The context carries internal identifiers only. It never carries names, contacts or
clinical text. It is signed with a shared secret and verified by the MCP broker; the
model can see an opaque token but cannot alter its contents.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Role(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    DOCTOR = "doctor"
    FRONT_DESK = "front_desk"
    PHARMACIST = "pharmacist"
    COMPLIANCE = "compliance"
    ADMIN = "admin"
    SERVICE = "service"


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_subject: str = Field(min_length=1, max_length=200)
    actor_role: Role
    patient_id: uuid.UUID | None = None
    clinic_ids: tuple[str, ...] = ()
    session_id: uuid.UUID | None = None
    trace_id: str = Field(min_length=1, max_length=64)
    locale: str = "en-IN"
    traffic_class: Literal["real", "synthetic"] = "real"
    issued_at: int
    expires_at: int
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=64)

    @field_validator("locale")
    @classmethod
    def _locale_shape(cls, value: str) -> str:
        if value not in {"en-IN", "hi-IN", "mr-IN"}:
            raise ValueError("unsupported locale")
        return value

    def is_expired(self, now: int | None = None) -> bool:
        return (now if now is not None else int(time.time())) >= self.expires_at


class ContextError(ValueError):
    """Raised when a signed context is missing, malformed, forged or expired."""


def _canonical_json(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_context(context: ExecutionContext, secret: str) -> str:
    if len(secret) < 32:
        raise ContextError("context secret must be at least 32 characters")
    body = _b64(_canonical_json(context.model_dump(mode="json")))
    signature = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def verify_context(
    token: str,
    secret: str,
    *,
    now: int | None = None,
    max_ttl_seconds: int = 300,
) -> ExecutionContext:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise ContextError("malformed context token") from exc
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    try:
        supplied = _unb64(signature)
    except (ValueError, TypeError) as exc:
        raise ContextError("malformed context signature") from exc
    if not hmac.compare_digest(expected, supplied):
        raise ContextError("invalid context signature")
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ContextError("malformed context payload") from exc
    try:
        context = ExecutionContext.model_validate(payload)
    except ValueError as exc:
        raise ContextError("invalid context payload") from exc
    current = now if now is not None else int(time.time())
    if context.is_expired(current):
        raise ContextError("context expired")
    if context.issued_at > current + 30:
        raise ContextError("context issued in the future")
    if context.expires_at - context.issued_at > max_ttl_seconds:
        raise ContextError("context lifetime exceeds policy")
    return context
