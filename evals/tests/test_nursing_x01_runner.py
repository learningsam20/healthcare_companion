"""G-13 nursing X-01 intent fixture shape (questions only; no authored drafts / WER)."""

from __future__ import annotations

import json
from pathlib import Path

from evals.harness.nursing_x01_runner import validate_case

ROOT = Path(__file__).resolve().parents[2]


def test_intent_fixture_validates() -> None:
    path = ROOT / "evals" / "sets" / "nursing_x01.jsonl"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 20
    for line in lines:
        errs = validate_case(json.loads(line))
        assert errs == [], errs


def test_validate_case_requires_decision_and_cite_flags() -> None:
    errs = validate_case({"id": "x", "question": "q"})
    assert "must_cite_required" in errs
    assert "must_not_invent_required" in errs
    assert "invalid_decision" in errs


def test_validate_case_accepts_well_formed_intent() -> None:
    assert (
        validate_case(
            {
                "id": "nx-unit",
                "question": "Summarise overnight vitals from the record only.",
                "must_cite": True,
                "must_not_invent": True,
                "decision": "accept",
            }
        )
        == []
    )


def test_draft_shape_requires_line_citations_when_present() -> None:
    """Citation structure check only — does not claim clinical quality scores."""
    missing = validate_case(
        {
            "id": "draft-missing-cite",
            "draft": {"lines": [{"text": "BP documented", "citations": []}]},
        }
    )
    assert "line_0_missing_citation" in missing

    ok = validate_case(
        {
            "id": "draft-with-cite",
            "draft": {
                "lines": [
                    {
                        "text": "BP documented",
                        "citations": [{"chunk_id": "c1"}],
                    }
                ]
            },
        }
    )
    assert ok == []


def test_expect_refuse_forbids_lines() -> None:
    assert validate_case({"expect_refuse": True, "draft": {"lines": []}}) == []
    assert "expected_refuse_but_has_lines" in validate_case(
        {"empty_evidence": True, "lines": [{"text": "invented", "citations": [{"id": "x"}]}]}
    )
