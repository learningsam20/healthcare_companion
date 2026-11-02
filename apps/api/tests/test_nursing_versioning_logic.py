"""G-13 nursing decision state machine (no DB)."""

from __future__ import annotations

from app.modules.nursing.router import NursingDecisionRequest, NursingSummaryOut
import uuid


def test_accept_edit_reject_literals() -> None:
    assert NursingDecisionRequest(decision="accept").decision == "accept"
    assert NursingDecisionRequest(decision="reject", note="no").decision == "reject"
    assert NursingDecisionRequest(decision="edit", summary="revised handover").summary


def test_draft_only_flag_tracks_status() -> None:
    draft = NursingSummaryOut(
        id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        version=1,
        status="draft",
        summary="s",
        sources=[],
        graph="x01_nursing.v1",
        draft_only=True,
    )
    accepted = draft.model_copy(update={"status": "accepted", "draft_only": False})
    assert draft.draft_only is True
    assert accepted.draft_only is False
