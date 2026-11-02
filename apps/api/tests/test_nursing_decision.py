"""X-01 nursing summary versioning schemas (unit-level)."""

from __future__ import annotations

from app.modules.nursing.router import NursingDecisionRequest, NursingSummaryOut
import uuid


def test_decision_request_accept() -> None:
    body = NursingDecisionRequest(decision="accept", note="ok")
    assert body.decision == "accept"


def test_summary_out_draft_flag() -> None:
    out = NursingSummaryOut(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        version=1,
        status="draft",
        summary="handover",
        sources=[],
        graph="x01_nursing.v1",
        draft_only=True,
    )
    assert out.draft_only is True
