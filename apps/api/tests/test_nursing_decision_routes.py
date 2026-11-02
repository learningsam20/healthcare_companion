"""G-13 nursing summary decision routes (accept/edit/reject + citations), unit-level mocks."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sahyog_common.errors import ProblemError

from app.core.security import AuthContext, Role
from app.modules.nursing.router import (
    NursingDecisionRequest,
    decide_nursing_summary,
)


class _Features:
    def enabled(self, key: str) -> bool:
        return key == "x01_nursing_summary"


def _context() -> AuthContext:
    return AuthContext(
        subject="doctor-nursing-test",
        roles=(Role.DOCTOR.value,),
        primary_role=Role.DOCTOR,
        patient_id=None,
        clinic_ids=(),
        locale="en-IN",
        traffic_class="synthetic",
        token_id=None,
    )


def _draft_row(*, sources: list[dict[str, Any]] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        version=1,
        status="draft",
        summary="Overnight vitals stable per chart.",
        sources=sources
        if sources is not None
        else [
            {
                "id": "chunk-vitals-1",
                "type": "document",
                "title": "Shift note",
                "locator": "page:1",
            }
        ],
        graph="x01_nursing.v1",
        model_alias="local_main",
        created_by="nurse-1",
        decided_by=None,
        decided_at=None,
        decision_note=None,
    )


class _FakeSession:
    def __init__(self, row: SimpleNamespace) -> None:
        self.row = row
        self.added: list[Any] = []
        self.committed = False
        self.refreshed: list[Any] = []
        self._max_version = row.version

    async def get(self, _model: Any, summary_id: uuid.UUID) -> SimpleNamespace | None:
        return self.row if summary_id == self.row.id else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def scalar(self, _statement: Any) -> int:
        return self._max_version

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.refreshed.append(obj)


def _patch_audit(monkeypatch: pytest.MonkeyPatch, audits: list[dict[str, Any]]) -> None:
    import app.modules.nursing.router as nursing

    class _Audit:
        def __init__(self, _session: Any) -> None:
            pass

        def append(self, **kwargs: Any) -> None:
            audits.append(kwargs)

    monkeypatch.setattr(nursing, "AuditRepository", _Audit)


@pytest.mark.asyncio
async def test_accept_keeps_citations_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _draft_row()
    session = _FakeSession(row)
    audits: list[dict[str, Any]] = []
    _patch_audit(monkeypatch, audits)

    out = await decide_nursing_summary(
        summary_id=row.id,
        body=NursingDecisionRequest(decision="accept", note="ok"),
        context=_context(),
        services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert out.status == "accepted"
    assert out.draft_only is False
    assert out.sources == row.sources
    assert out.sources[0]["id"] == "chunk-vitals-1"
    assert session.committed is True
    assert audits[-1]["action"] == "nursing.summary_accept"
    assert audits[-1]["metadata"]["decision"] == "accept"


@pytest.mark.asyncio
async def test_reject_marks_draft_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _draft_row()
    session = _FakeSession(row)
    audits: list[dict[str, Any]] = []
    _patch_audit(monkeypatch, audits)

    out = await decide_nursing_summary(
        summary_id=row.id,
        body=NursingDecisionRequest(decision="reject", note="incomplete"),
        context=_context(),
        services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert out.status == "rejected"
    assert out.decision_note == "incomplete"
    assert out.sources[0]["id"] == "chunk-vitals-1"
    assert audits[-1]["action"] == "nursing.summary_reject"


@pytest.mark.asyncio
async def test_edit_creates_new_version_preserving_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _draft_row()
    session = _FakeSession(row)
    audits: list[dict[str, Any]] = []
    _patch_audit(monkeypatch, audits)

    out = await decide_nursing_summary(
        summary_id=row.id,
        body=NursingDecisionRequest(
            decision="edit",
            summary="Revised handover with same citations.",
            note="clarified vitals",
        ),
        context=_context(),
        services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert row.status == "rejected"
    assert len(session.added) == 1
    edited = session.added[0]
    assert edited.status == "edited"
    assert edited.version == 2
    assert edited.summary == "Revised handover with same citations."
    assert edited.sources == row.sources
    assert out.status == "edited"
    assert out.version == 2
    assert out.sources[0]["locator"] == "page:1"
    assert audits[-1]["action"] == "nursing.summary_edit"


@pytest.mark.asyncio
async def test_edit_without_summary_fails() -> None:
    row = _draft_row()
    session = _FakeSession(row)
    with pytest.raises(ProblemError) as exc:
        await decide_nursing_summary(
            summary_id=row.id,
            body=NursingDecisionRequest(decision="edit", summary="  "),
            context=_context(),
            services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )
    assert exc.value.code == "nursing_edit_required"


@pytest.mark.asyncio
async def test_already_decided_is_conflict() -> None:
    row = _draft_row()
    row.status = "accepted"
    session = _FakeSession(row)
    with pytest.raises(ProblemError) as exc:
        await decide_nursing_summary(
            summary_id=row.id,
            body=NursingDecisionRequest(decision="accept"),
            context=_context(),
            services=SimpleNamespace(features=_Features()),  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )
    assert exc.value.code == "nursing_summary_not_draft"
