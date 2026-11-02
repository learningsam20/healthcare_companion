from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import Settings
from app.core.security import AuthContext, Role, get_auth_context
from fastapi.security import HTTPAuthorizationCredentials
from sahyog_common.errors import ProblemError


def _context(
    role: Role, *, subject: str = "subject-1", patient_id: uuid.UUID | None = None
) -> AuthContext:
    return AuthContext(
        subject=subject,
        roles=(role.value,),
        primary_role=role,
        patient_id=patient_id,
        clinic_ids=(),
        locale="en-IN",
        traffic_class="synthetic",
        token_id=None,
    )


class _FakeSession:
    def __init__(self, consent: Any) -> None:
        self._consent = consent

    async def scalar(self, statement: Any) -> Any:
        return self._consent

    async def scalars(self, statement: Any) -> list[Any]:
        return [self._consent] if self._consent is not None else []


def _request() -> Any:
    return SimpleNamespace(state=SimpleNamespace())


async def _resolve(
    monkeypatch: pytest.MonkeyPatch,
    *,
    context: AuthContext,
    header: str | None,
    consent: Any = None,
) -> AuthContext:
    monkeypatch.setattr("app.core.security.verify_token", lambda token, settings: context)
    return await get_auth_context(
        request=_request(),
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"),
        settings=Settings(),
        session=_FakeSession(consent),  # type: ignore[arg-type]
        consent_header=header,
    )


async def test_consent_header_binds_selected_patient(monkeypatch: pytest.MonkeyPatch) -> None:
    consent_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    consent = SimpleNamespace(id=consent_id, patient_id=patient_id)
    context = await _resolve(
        monkeypatch,
        context=_context(Role.CAREGIVER),
        header=str(consent_id),
        consent=consent,
    )
    assert context.patient_id == patient_id
    assert context.consent_id == consent_id


async def test_consent_header_rejected_for_non_caregiver(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProblemError) as excinfo:
        await _resolve(
            monkeypatch,
            context=_context(Role.PATIENT),
            header=str(uuid.uuid4()),
        )
    assert excinfo.value.status == 403
    assert excinfo.value.code == "context_forbidden"


async def test_consent_header_rejects_malformed_value(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProblemError) as excinfo:
        await _resolve(monkeypatch, context=_context(Role.CAREGIVER), header="not-a-uuid")
    assert excinfo.value.status == 400
    assert excinfo.value.code == "context_invalid"


async def test_consent_header_requires_active_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProblemError) as excinfo:
        await _resolve(
            monkeypatch,
            context=_context(Role.CAREGIVER),
            header=str(uuid.uuid4()),
            consent=None,
        )
    assert excinfo.value.status == 403
    assert excinfo.value.code == "consent_required"


async def test_token_patient_scope_attaches_matching_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patient_id = uuid.uuid4()
    consent_id = uuid.uuid4()
    context = await _resolve(
        monkeypatch,
        context=_context(Role.CAREGIVER, patient_id=patient_id),
        header=None,
        consent=SimpleNamespace(id=consent_id, patient_id=patient_id),
    )
    assert context.patient_id == patient_id
    assert context.consent_id == consent_id


async def test_consent_header_never_expands_other_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _resolve(
        monkeypatch,
        context=_context(Role.DOCTOR, patient_id=uuid.uuid4()),
        header=None,
    )
    assert context.consent_id is None


def test_consent_default_scopes_are_unique() -> None:
    from app.modules.consents.schemas import ConsentCreate

    body = ConsentCreate(
        caregiver_subject="caregiver-1",
        scopes=["chat", "records", "chat"],  # type: ignore[list-item]
    )
    assert body.scopes == ["chat", "records"]
    assert body.purpose == "care"


def test_consent_expiry_validation_helper() -> None:
    from app.modules.consents.router import _aware

    naive = dt.datetime(2026, 12, 1, 9, 0)
    assert _aware(naive) == naive.replace(tzinfo=dt.UTC)
    aware = dt.datetime(2026, 12, 1, 9, 0, tzinfo=dt.UTC)
    assert _aware(aware) is aware
    assert _aware(None) is None
