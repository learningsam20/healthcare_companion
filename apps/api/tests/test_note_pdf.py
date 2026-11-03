"""Unit tests for signed clinical note PDF export."""

from __future__ import annotations

import datetime as dt
import uuid

from app.modules.scribe.note_pdf import render_clinical_note_pdf
from pypdf import PdfReader


def test_render_clinical_note_pdf_has_header_sections_and_footer() -> None:
    note_id = uuid.uuid4()
    patient_id = uuid.uuid4()
    pdf_bytes = render_clinical_note_pdf(
        note_id=note_id,
        title="Consultation note — 03 Nov 2026",
        patient_name="Priya Sharma",
        patient_id=patient_id,
        version=2,
        language="en-IN",
        status="signed",
        signed_by="doctor@sahyog.example",
        signed_at=dt.datetime(2026, 11, 3, 10, 30, tzinfo=dt.UTC),
        signed_hash="abc123def456" * 4,
        content={
            "subjective": [{"text": "fever for two days", "source_turn_ids": [], "unsourced": False}],
            "objective": [{"text": "temp 38.4 C", "source_turn_ids": [], "unsourced": False}],
            "assessment": [{"text": "viral fever", "source_turn_ids": [], "unsourced": False}],
            "plan": [{"text": "rest and fluids", "source_turn_ids": [], "unsourced": False}],
            "follow_up": {"text": "return if worse in 48 hours"},
            "medicines": [
                {
                    "name": "Paracetamol",
                    "dose": "500 mg",
                    "frequency": "TDS",
                    "duration": "3 days",
                    "instructions": "after food",
                }
            ],
        },
        doctor_name="Dr Mehta",
        clinic_code="PUNE-01",
        org_name="Sahyog Care Companion",
    )

    assert pdf_bytes.startswith(b"%PDF")
    reader = PdfReader(__import__("io").BytesIO(pdf_bytes))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Sahyog Care Companion" in text
    assert "Consultation note" in text
    assert "Priya Sharma" in text
    assert "Subjective" in text
    assert "fever for two days" in text or "Fever for two days" in text
    assert "Paracetamol" in text
    assert "Digital signature" in text
    assert str(note_id) in text
    assert "For authorised care-team use only" in text
    assert "Page 1" in text
