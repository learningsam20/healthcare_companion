"""G-13 live-draft harness + clinician grade ingestion (no network, no clinical claim)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from evals.harness.nursing_x01_grades import evaluate
from evals.harness.nursing_x01_live import (
    GRADE_COLUMNS,
    build_artefact,
    generate_draft,
    load_cases,
    write_grade_template,
)

ROOT = Path(__file__).resolve().parents[2]


class _Client:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.calls: list[dict[str, Any]] = []

    def post(self, path: str, body: dict[str, Any], *, username: str) -> Any:
        self.calls.append({"path": path, "body": body, "username": username})
        if body["query"] in self.fail_on:
            raise RuntimeError("feature_disabled")
        return {
            "id": f"s-{len(self.calls)}",
            "version": 1,
            "status": "draft",
            "summary": "text",
            "sources": [{"id": "c1"}],
            "graph": "x01_nursing.v1",
            "model_alias": "local",
        }


def _drafts(count: int = 20) -> dict[str, Any]:
    cases = [
        {"id": f"nx01-{i:02d}", "question": f"q{i}", "language": "en-IN"} for i in range(count)
    ]
    client = _Client()
    rows = [generate_draft(client, c, patient_id="p", username="doctor.rao") for c in cases]
    return build_artefact(rows, patient_id="p", username="doctor.rao", base_url="http://x")


def _grade_rows(artefact: dict[str, Any], **overrides: str) -> list[dict[str, str]]:
    rows = []
    for draft in artefact["drafts"]:
        row = {
            "case_id": draft["case_id"],
            "summary_id": draft["summary_id"],
            "grader_id": "dr-example",
            "grader_role": "nurse_educator",
            "grader_attested": "true",
            "accuracy_1_5": "5",
            "citation_support_1_5": "5",
            "invented_content": "no",
            "clinically_acceptable": "accept",
            "notes": "",
        }
        row.update(overrides)
        rows.append(row)
    return rows


def test_generate_draft_records_live_response_and_errors() -> None:
    client = _Client(fail_on={"bad"})
    ok = generate_draft(
        client, {"id": "a", "question": "good"}, patient_id="p", username="doctor.rao"
    )
    assert ok["summary_id"] == "s-1" and ok["source_count"] == 1
    assert client.calls[0]["path"] == "/api/v1/nursing/summary"
    bad = generate_draft(client, {"id": "b", "question": "bad"}, patient_id="p", username="u")
    assert "summary_id" not in bad and "feature_disabled" in bad["error"]


def test_artefact_is_live_and_never_claims_a_score() -> None:
    artefact = _drafts(3)
    assert artefact["live"] is True
    assert artefact["clinical_quality_scored"] is False
    assert artefact["generated"] == 3 and artefact["errors"] == 0


def test_fixture_loads_and_template_skips_errored_cases(tmp_path: Path) -> None:
    cases = load_cases(ROOT / "evals" / "sets" / "nursing_x01.jsonl")
    assert len(cases) == 20
    drafts = [
        {"case_id": "a", "summary_id": "s1"},
        {"case_id": "b", "error": "RuntimeError: down"},
    ]
    out = tmp_path / "grades.csv"
    assert write_grade_template(out, drafts) == 1
    with out.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == GRADE_COLUMNS
        assert [row["case_id"] for row in reader] == ["a"]


def test_complete_attested_grades_pass_but_never_close_gap() -> None:
    artefact = _drafts()
    report = evaluate(artefact, _grade_rows(artefact))
    assert report["status"] == "graded_pass"
    assert report["graded_cases"] == 20
    assert report["closes_gap"] is False


def test_unattested_or_partial_grades_are_not_counted() -> None:
    artefact = _drafts()
    unattested = evaluate(artefact, _grade_rows(artefact, grader_attested="false"))
    assert unattested["status"] == "invalid"
    assert unattested["graded_cases"] == 0
    partial = evaluate(artefact, _grade_rows(artefact)[:10])
    assert partial["status"] == "incomplete"


def test_grades_for_unknown_or_fixture_drafts_are_rejected() -> None:
    artefact = _drafts()
    rows = _grade_rows(artefact)
    rows[0]["summary_id"] = "not-live"
    report = evaluate(artefact, rows)
    assert report["status"] == "invalid"
    assert any("not a live draft" in e for e in report["errors"])
    not_live = {"kind": "nursing_x01_shape", "live": False, "drafts": []}
    assert evaluate(not_live, [])["status"] == "invalid"


def test_invented_content_fails_acceptance() -> None:
    artefact = _drafts()
    rows = _grade_rows(artefact)
    rows[3]["invented_content"] = "yes"
    assert evaluate(artefact, rows)["status"] == "graded_fail"
