"""Unit tests for G-12 / G-19 compliance attestation helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.modules.compliance import service as compliance
from app.repositories.models import ComplianceAttestation
from sahyog_common.errors import ProblemError


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        return _Scalars(self._rows)


class _Session:
    def __init__(self):
        self.added = []
        self.attestation: ComplianceAttestation | None = None
        self.gov: dict = {}

    async def execute(self, stmt):  # noqa: ANN001
        # Heuristic: GovernanceSetting vs ComplianceAttestation
        compiled = str(getattr(stmt, "compile", lambda: stmt)())
        text = compiled.lower()
        if "governance_settings" in text or "governancesetting" in text:
            rows = [SimpleNamespace(key=k, value={"value": v}) for k, v in self.gov.items()]
            return _Result(rows=rows)
        return _Result(row=self.attestation)

    async def flush(self):
        for obj in self.added:
            if isinstance(obj, ComplianceAttestation):
                self.attestation = obj

    def add(self, obj):  # noqa: ANN001
        self.added.append(obj)
        if isinstance(obj, ComplianceAttestation):
            self.attestation = obj


class _Storage:
    async def put(self, *, key: str, data: bytes, content_type: str):
        assert data


@pytest.mark.asyncio
async def test_attestation_requires_checkbox_and_report():
    session = _Session()
    with pytest.raises(ProblemError) as exc:
        await compliance.upload_and_attest(
            session,  # type: ignore[arg-type]
            _Storage(),  # type: ignore[arg-type]
            kind=compliance.CLINICAL,
            status="attested",
            approver_name="Dr Test",
            approver_role="CMO",
            attestation_checked=False,
            attestation_text="I attest",
            notes=None,
            filename="report.pdf",
            content_type="application/pdf",
            data=b"%PDF",
            actor="admin",
            actor_role="admin",
            trace_id=None,
        )
    assert exc.value.code == "attestation_required"


@pytest.mark.asyncio
async def test_attestation_success_sets_status(monkeypatch: pytest.MonkeyPatch):
    session = _Session()
    monkeypatch.setattr(
        "app.modules.compliance.service.AuditRepository",
        lambda _session: MagicMock(append=MagicMock()),
    )
    row = await compliance.upload_and_attest(
        session,  # type: ignore[arg-type]
        _Storage(),  # type: ignore[arg-type]
        kind=compliance.CLINICAL,
        status="attested",
        approver_name="Dr Test",
        approver_role="CMO",
        attestation_checked=True,
        attestation_text="I attest",
        notes=None,
        filename="report.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4",
        actor="admin",
        actor_role="admin",
        trace_id="abc",
    )
    assert row.status == "attested"
    assert row.report_sha256
    public = compliance.attestation_public(row, kind=compliance.CLINICAL)
    assert public["claim"] == "attested_report_on_file_not_regulatory_clearance"
    assert public["has_report"] is True


@pytest.mark.asyncio
async def test_dpdp_disapproved_blocks():
    session = _Session()
    session.attestation = ComplianceAttestation(
        kind=compliance.DPDP, status="disapproved"
    )
    assert await compliance.dpdp_blocks_processing(session) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dpdp_enforce_blocks_when_missing():
    session = _Session()
    session.gov = {"dpdp_enforce": True}
    session.attestation = None
    assert await compliance.dpdp_blocks_processing(session) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dpdp_default_allows_when_not_enforced():
    session = _Session()
    session.gov = {"dpdp_enforce": False}
    session.attestation = None
    assert await compliance.dpdp_blocks_processing(session) is False  # type: ignore[arg-type]


def test_public_not_attested_claim():
    public = compliance.attestation_public(None, kind=compliance.CLINICAL)
    assert public["status"] == "not_attested"
    assert public["claim"] == "not_a_validated_medical_device"
