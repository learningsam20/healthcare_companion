from __future__ import annotations

import time
import uuid

import pytest
from sahyog_common.context import (
    ContextError,
    ExecutionContext,
    Role,
    sign_context,
    verify_context,
)

SECRET = "test-context-secret-that-is-long-enough-123"


def _context(**overrides: object) -> ExecutionContext:
    now = int(time.time())
    payload: dict[str, object] = {
        "actor_subject": "keycloak-subject-1",
        "actor_role": Role.PATIENT,
        "patient_id": uuid.UUID("6f3f7f5e-0d2a-4f45-9a65-2f8f6f2f0c11"),
        "clinic_ids": ("BLR-01",),
        "session_id": uuid.uuid4(),
        "trace_id": "trace-abc",
        "locale": "en-IN",
        "traffic_class": "real",
        "issued_at": now,
        "expires_at": now + 120,
    }
    payload.update(overrides)
    return ExecutionContext.model_validate(payload)


def test_round_trip_preserves_internal_ids() -> None:
    context = _context()
    restored = verify_context(sign_context(context, SECRET), SECRET)
    assert restored == context
    assert restored.patient_id == context.patient_id


def test_tampered_payload_is_rejected() -> None:
    token = sign_context(_context(), SECRET)
    body, signature = token.split(".", 1)
    forged = body[:-2] + ("AA" if body[-2:] != "AA" else "BB")
    with pytest.raises(ContextError, match="invalid context signature"):
        verify_context(f"{forged}.{signature}", SECRET)


def test_wrong_secret_is_rejected() -> None:
    token = sign_context(_context(), SECRET)
    with pytest.raises(ContextError, match="invalid context signature"):
        verify_context(token, "another-test-secret-that-is-long-enough")


def test_expired_context_is_rejected() -> None:
    now = int(time.time())
    token = sign_context(_context(issued_at=now - 600, expires_at=now - 300), SECRET)
    with pytest.raises(ContextError, match="expired"):
        verify_context(token, SECRET)


def test_excessive_lifetime_is_rejected() -> None:
    now = int(time.time())
    token = sign_context(_context(issued_at=now, expires_at=now + 900), SECRET)
    with pytest.raises(ContextError, match="lifetime exceeds policy"):
        verify_context(token, SECRET, max_ttl_seconds=300)


def test_future_issue_time_is_rejected() -> None:
    now = int(time.time())
    token = sign_context(_context(issued_at=now + 120, expires_at=now + 240), SECRET)
    with pytest.raises(ContextError, match="issued in the future"):
        verify_context(token, SECRET)


def test_short_secret_cannot_sign() -> None:
    with pytest.raises(ContextError, match="at least 32"):
        sign_context(_context(), "short")


def test_unknown_fields_are_forbidden() -> None:
    payload = _context().model_dump(mode="json") | {"patient_name": "Asha"}
    with pytest.raises(ValueError):
        ExecutionContext.model_validate(payload)


def test_unsupported_locale_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported locale"):
        _context(locale="fr-FR")
