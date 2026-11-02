"""The deterministic safety gate must remain the sole release blocker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.harness.framework_runner import main, release_gate
from evals.harness.runner import SuiteResult, run_safety_gate


def test_deterministic_safety_gate_passes_60_of_60() -> None:
    gate = run_safety_gate()
    assert gate["status"] == "passed"
    assert gate["case_count"] == 60
    assert gate["passed_cases"] == 60
    assert gate["failed_cases"] == 0
    assert gate["framework_scores_used"] is False
    assert all(suite["status"] == "passed" for suite in gate["suites"])


def test_framework_metrics_cannot_override_a_failed_deterministic_case() -> None:
    result = SuiteResult(
        suite="w1",
        framework="ragas",
        framework_version="0.4.3",
        dataset_hash="synthetic",
        cases=[
            {
                "id": "w1-rf-001",
                "check": "red_flag",
                "passed": False,
                "failures": ["expected emergency handoff"],
            },
            {
                "id": "rag-en-001",
                "check": "ragas",
                "passed": True,
                "failures": [],
                "scores": {"faithfulness": 1.0},
            },
        ],
        metrics={"case_pass_rate": 0.5, "faithfulness": 1.0, "answer_relevancy": 1.0},
    )
    assert result.status == "failed"


def test_release_gate_blocks_on_failed_safety_and_ignores_framework_scores() -> None:
    blocked = release_gate({"status": "failed", "failed_cases": 1})
    assert blocked["status"] == "blocked"
    assert blocked["framework_scores_used"] is False
    assert blocked["framework_scores_can_override"] is False

    passed = release_gate({"status": "passed", "failed_cases": 0})
    assert passed["status"] == "passed"


def test_no_judge_run_validates_suites_and_reports_pending_calibration(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"
    calibration_path = tmp_path / "calibration.json"
    code = main(
        [
            "--suite",
            "all",
            "--no-judge",
            "--report",
            str(report_path),
            "--calibration-out",
            str(calibration_path),
            "--quiet",
        ]
    )
    assert code == 0
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["mode"] == "no_judge"
    assert report["status"] == "not_run"
    assert report["release_gate"]["status"] == "passed"
    assert report["safety_gate"]["case_count"] == 60
    assert report["calibration"]["status"] == "pending"
    assert report["calibration"]["calibrated_by"] == "unreviewed"
    assert [run["suite"] for run in report["framework_runs"]] == ["rag_w3", "qa_x01"]
    assert all(run["status"] == "not_run" for run in report["framework_runs"])
    assert all(run["metrics"] == {} for run in report["framework_runs"])
    artifact: dict[str, Any] = json.loads(calibration_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "pending"
    assert artifact["human_review_performed"] is False


def test_framework_suite_mismatch_is_rejected(tmp_path: Path) -> None:
    code = main(
        [
            "--suite",
            "rag_w3",
            "--framework",
            "deepeval",
            "--no-judge",
            "--calibration-out",
            str(tmp_path / "calibration.json"),
            "--quiet",
        ]
    )
    assert code == 2
