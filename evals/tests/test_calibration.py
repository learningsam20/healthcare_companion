"""Calibration fixture, reviewer attestation and agreement-math tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.harness.calibration import (
    build_calibration_artifact,
    compute_agreement,
    load_calibration,
    load_judge_labels,
    load_reviewer_labels,
)
from evals.harness.errors import CalibrationError, EvalSchemaError


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _reviewer_payload(labels: dict[str, str], reviewer_id: str = "reviewer-01") -> dict[str, Any]:
    return {
        "reviewer_id": reviewer_id,
        "reviewed_at": "2026-10-25",
        "attested_human_review": True,
        "labels": labels,
    }


def test_shipped_calibration_is_unreviewed_and_pending() -> None:
    calibration = load_calibration()
    assert len(calibration.pairs) == 10
    assert len(calibration.items) == 20
    artifact = build_calibration_artifact(calibration)
    assert artifact["status"] == "pending"
    assert artifact["judge_calibration_status"] == "pending_human_review"
    assert artifact["calibrated_by"] == "unreviewed"
    assert artifact["human_review_performed"] is False
    assert artifact["label_counts"] == {"good": 10, "bad": 10}
    assert artifact["agreement"]["reviewer_vs_fixture"]["available"] is False
    assert artifact["agreement"]["judge_vs_reviewer"]["available"] is False


def test_reviewer_file_without_attestation_is_rejected(tmp_path: Path) -> None:
    calibration = load_calibration()
    labels = calibration.fixture_labels()
    payload = _reviewer_payload(labels)
    payload["attested_human_review"] = False
    path = _write_json(tmp_path / "reviewer.json", payload)
    with pytest.raises(EvalSchemaError, match="attested_human_review"):
        load_reviewer_labels(path, calibration)


def test_provisional_fixture_file_without_attestation_stays_pending(tmp_path: Path) -> None:
    calibration = load_calibration()
    provisional = {
        "reviewer_id": "provisional_fixture",
        "reviewed_at": "2026-10-31",
        "attested_human_review": False,
        "review_mode": "fixture_consistency_smoke",
        "calibrated_by": "provisional_fixture",
        "labels": calibration.fixture_labels(),
    }
    path = _write_json(tmp_path / "reviewer_provisional.json", provisional)
    with pytest.raises(EvalSchemaError, match="attested_human_review"):
        load_reviewer_labels(path, calibration)
    artifact = build_calibration_artifact(calibration)
    assert artifact["status"] == "pending"
    assert artifact["judge_calibration_status"] == "pending_human_review"
    assert artifact["human_review_performed"] is False


def test_reserved_reviewer_id_is_rejected(tmp_path: Path) -> None:
    calibration = load_calibration()
    path = _write_json(
        tmp_path / "reviewer.json", _reviewer_payload(calibration.fixture_labels(), "system")
    )
    with pytest.raises(EvalSchemaError, match="reserved"):
        load_reviewer_labels(path, calibration)


def test_partial_review_stays_pending(tmp_path: Path) -> None:
    calibration = load_calibration()
    labels = calibration.fixture_labels()
    partial = dict(sorted(labels.items())[:10])
    reviewer = load_reviewer_labels(
        _write_json(tmp_path / "reviewer.json", _reviewer_payload(partial)), calibration
    )
    artifact = build_calibration_artifact(calibration, reviewer=reviewer)
    assert artifact["status"] == "pending"
    assert artifact["calibrated_by"] == "reviewer-01"
    assert artifact["human_review_performed"] is True
    assert artifact["review"]["coverage"] == 0.5
    assert len(artifact["review"]["missing_item_ids"]) == 10
    assert artifact["agreement"]["reviewer_vs_fixture"]["available"] is False


def test_complete_review_marks_reviewed_and_computes_fixture_agreement(
    tmp_path: Path,
) -> None:
    calibration = load_calibration()
    labels = calibration.fixture_labels()
    reviewer = load_reviewer_labels(
        _write_json(tmp_path / "reviewer.json", _reviewer_payload(labels)), calibration
    )
    artifact = build_calibration_artifact(calibration, reviewer=reviewer)
    assert artifact["status"] == "reviewed"
    assert artifact["judge_calibration_status"] == "pending_judge_verdicts"
    assert artifact["calibrated_by"] == "reviewer-01"
    assert artifact["human_review_performed"] is True
    agreement = artifact["agreement"]["reviewer_vs_fixture"]
    assert agreement["available"] is True
    assert agreement["observed_agreement"] == 1.0
    assert agreement["cohen_kappa"] == 1.0
    judge_agreement = artifact["agreement"]["judge_vs_reviewer"]
    assert judge_agreement["available"] is False
    assert "judge verdicts" in judge_agreement["reason"]


def test_agreement_math_known_values() -> None:
    truth = {"a": "good", "b": "bad", "c": "good", "d": "bad"}
    predicted = {"a": "good", "b": "good", "c": "bad", "d": "bad"}
    agreement = compute_agreement(truth, predicted)
    assert agreement.n == 4
    assert agreement.observed_agreement == 0.5
    assert agreement.cohen_kappa == 0.0
    assert agreement.confusion == {
        "good": {"good": 1, "bad": 1},
        "bad": {"good": 1, "bad": 1},
    }
    assert agreement.disagreements == ("b", "c")


def test_agreement_math_known_kappa() -> None:
    truth = {"1": "good", "2": "good", "3": "bad", "4": "bad", "5": "good", "6": "bad"}
    predicted = {"1": "good", "2": "good", "3": "bad", "4": "good", "5": "bad", "6": "bad"}
    agreement = compute_agreement(truth, predicted)
    assert agreement.observed_agreement == pytest.approx(0.666667, abs=1e-6)
    assert agreement.cohen_kappa == pytest.approx(0.333333, abs=1e-6)
    assert agreement.disagreements == ("4", "5")


def test_agreement_undefined_kappa_when_one_class_only() -> None:
    agreement = compute_agreement({"a": "good", "b": "good"}, {"a": "good", "b": "good"})
    assert agreement.observed_agreement == 1.0
    assert agreement.cohen_kappa is None


def test_agreement_rejects_mismatched_item_sets() -> None:
    with pytest.raises(CalibrationError, match="same items"):
        compute_agreement({"a": "good"}, {"b": "bad"})


def test_judge_vs_reviewer_agreement_is_computed_only_when_both_complete(
    tmp_path: Path,
) -> None:
    calibration = load_calibration()
    reviewer_labels = calibration.fixture_labels()
    judge_labels = dict(reviewer_labels)
    judge_labels["cal-p01-good"] = "bad"
    judge_labels["cal-p01-bad"] = "good"

    reviewer = load_reviewer_labels(
        _write_json(tmp_path / "reviewer.json", _reviewer_payload(reviewer_labels)), calibration
    )
    judge = load_judge_labels(
        _write_json(
            tmp_path / "judge.json",
            {
                "judge_alias": "judge",
                "produced_at": "2026-10-25",
                "labels": judge_labels,
            },
        ),
        calibration,
    )
    artifact = build_calibration_artifact(calibration, reviewer=reviewer, judge=judge)
    assert artifact["status"] == "calibrated"
    assert artifact["judge_calibration_status"] == "calibrated"
    assert artifact["meets_kappa_target"] is True
    agreement = artifact["agreement"]["judge_vs_reviewer"]
    assert agreement["available"] is True
    assert agreement["n"] == 20
    assert agreement["observed_agreement"] == 0.9
    assert agreement["cohen_kappa"] == 0.8
    assert agreement["meets_target"] is True
    assert set(agreement["disagreements"]) == {"cal-p01-good", "cal-p01-bad"}


def test_judge_labels_without_reviewer_stay_pending(tmp_path: Path) -> None:
    calibration = load_calibration()
    labels = calibration.fixture_labels()
    judge = load_judge_labels(
        _write_json(
            tmp_path / "judge.json",
            {"judge_alias": "judge", "produced_at": "2026-10-25", "labels": labels},
        ),
        calibration,
    )
    artifact = build_calibration_artifact(calibration, judge=judge)
    assert artifact["status"] == "pending"
    assert artifact["judge_calibration_status"] == "pending_human_review"
    assert artifact["calibrated_by"] == "unreviewed"
    assert artifact["judge"]["labels_supplied"] is True
    assert artifact["agreement"]["judge_vs_reviewer"]["available"] is False
