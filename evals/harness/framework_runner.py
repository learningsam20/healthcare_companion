#!/usr/bin/env python3
"""Focused runner for answer-bearing RAGAS/DeepEval suites and judge calibration.

Unlike the deterministic harness (``evals/harness/runner.py``), this runner selects the
answer-bearing W3/X-01 fixtures, invokes an optional framework adapter through the
configured LiteLLM alias, and writes a judge-calibration artefact.  The deterministic
safety gate is run in the same process and its result is the only release gate:
framework scores are reported separately and can never override it.

Usage examples are documented in ``evals/README.md``.  Model-dependent runs require
``LITELLM_BASE_URL`` and ``LITELLM_MASTER_KEY``; use ``--no-judge`` for an offline
validation run that produces no framework score.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.harness.answer_suites import (  # noqa: E402
    LANGUAGES,
    QA_SPEC,
    RAG_SPEC,
    ROOT,
    SUITE_SPECS,
    AnswerSuite,
    AnswerSuiteSpec,
    load_answer_suites,
)
from evals.harness.calibration import (  # noqa: E402
    CALIBRATION_PATH,
    CalibrationSet,
    ReviewerLabels,
    build_calibration_artifact,
    load_calibration,
    load_judge_labels,
    load_reviewer_labels,
    write_calibration_artifact,
)
from evals.harness.errors import AdapterUnavailable, EvalError  # noqa: E402
from evals.harness.runner import (  # noqa: E402
    resolve_alias,
    run_framework_adapter,
    run_safety_gate,
)

REQUIRED_JUDGE_ENV: Final[tuple[str, ...]] = ("LITELLM_BASE_URL", "LITELLM_MASTER_KEY")
DEFAULT_CALIBRATION_OUT: Final = ROOT / "evals" / "reports" / "judge_calibration.json"
FRAMEWORK_LIMITATIONS: Final[tuple[str, ...]] = (
    "Answer fixtures are authored synthetic fixtures, not outputs of a live Sahyog pipeline.",
    "Framework scores are answer-quality signals, not clinical validation or a safety gate.",
    "A judge is untrusted until a complete human review and judge-vs-human agreement exist.",
    "No score is recorded in a fixture; scores only exist after a framework run.",
)


def _selected_specs(suite: str, framework: str) -> list[AnswerSuiteSpec]:
    if suite == "all":
        specs = [RAG_SPEC, QA_SPEC]
    else:
        spec = SUITE_SPECS.get(suite)
        if spec is None:
            raise EvalError(
                f"unknown answer-bearing suite {suite!r}; available: {sorted(SUITE_SPECS)}"
            )
        specs = [spec]
    if framework != "auto":
        mismatched = [spec.name for spec in specs if spec.framework != framework]
        if mismatched:
            raise EvalError(
                f"suite(s) {mismatched} use a different framework than {framework!r}; "
                "select the matching suite or use --framework auto"
            )
    return specs


def release_gate(safety_gate: dict[str, Any]) -> dict[str, Any]:
    """Derive the release gate from deterministic safety only.

    There is deliberately no framework parameter here: no RAGAS/DeepEval score can
    change ``blocked`` into ``passed``.
    """
    passed = safety_gate.get("status") == "passed" and safety_gate.get("failed_cases") == 0
    return {
        "status": "passed" if passed else "blocked",
        "basis": "deterministic_red_flag_and_provenance",
        "framework_scores_used": False,
        "framework_scores_can_override": False,
    }


def _language_slices(
    suite: AnswerSuite, case_results: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_language: dict[str, list[dict[str, Any]]] = {language: [] for language in LANGUAGES}
    result_by_id = {
        str(result.get("id")): result for result in case_results if isinstance(result, dict)
    }
    for case in suite.cases:
        result = result_by_id.get(case.id)
        if result is not None:
            by_language[case.language].append(result)
    slices: dict[str, dict[str, Any]] = {}
    for language, results in by_language.items():
        if not results:
            continue
        metric_values: dict[str, list[float]] = {}
        for result in results:
            raw_scores = result.get("scores")
            if not isinstance(raw_scores, dict):
                continue
            for key, value in raw_scores.items():
                if isinstance(value, int | float):
                    metric_values.setdefault(str(key), []).append(float(value))
        slices[language] = {
            "case_count": sum(1 for case in suite.cases if case.language == language),
            "scored_cases": len(results),
            "mean_scores": {
                key: round(sum(values) / len(values), 6)
                for key, values in metric_values.items()
                if values
            },
        }
    return slices


def _missing_judge_env() -> list[str]:
    return [name for name in REQUIRED_JUDGE_ENV if not os.environ.get(name)]


def _run_suite(suite: AnswerSuite, *, judge_alias: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "suite": suite.spec.name,
        "framework": suite.spec.framework,
        "dataset_hash": suite.dataset_hash,
        "case_count": len(suite.cases),
        "language_slices": {},
        "case_results": [],
        "metrics": {},
        "framework_version": None,
        "error": None,
    }
    try:
        outcome = run_framework_adapter(
            suite.spec.framework, suite.adapter_cases(), judge_alias=judge_alias
        )
    except AdapterUnavailable as exc:
        return {**base, "status": "unavailable", "error": str(exc)}
    except EvalError as exc:
        return {**base, "status": "error", "error": str(exc)}
    except Exception as exc:  # a judge outage must be visible, not silently skipped
        return {
            **base,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }
    metrics = {str(key): float(value) for key, value in outcome.get("metrics", {}).items()}
    case_results = [result for result in outcome.get("cases", []) if isinstance(result, dict)]
    return {
        **base,
        "status": "scored",
        "framework_version": str(outcome.get("framework_version", "unknown")),
        "metrics": metrics,
        "case_results": case_results,
        "language_slices": _language_slices(suite, case_results),
    }


def _suite_metadata(suite: AnswerSuite) -> dict[str, Any]:
    return {
        "suite": suite.spec.name,
        "framework": suite.spec.framework,
        "dataset_hash": suite.dataset_hash,
        "case_count": len(suite.cases),
        "language_case_counts": {
            language: count for language, count in suite.language_counts().items() if count
        },
        "case_results": [],
        "metrics": {},
        "framework_version": None,
        "error": None,
    }


def _write_json(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summary(report: dict[str, Any]) -> str:
    gate = report.get("release_gate")
    gate_status = gate["status"] if isinstance(gate, dict) else "n/a"
    lines = [
        f"framework run {report['run_id']} · mode={report['mode']} · {report['status']}",
        f"  safety gate: {gate_status}",
    ]
    for run in report.get("framework_runs", []):
        metrics = ", ".join(f"{key}={value:.3f}" for key, value in run["metrics"].items())
        suffix = f" {metrics}" if metrics else ""
        lines.append(
            f"  {run['suite']}/{run['framework']}: {run['status']} "
            f"({run['case_count']} cases){suffix}"
        )
        if run.get("error"):
            lines.append(f"    error: {run['error']}")
    calibration = report.get("calibration") or {}
    lines.append(
        f"  calibration: {calibration.get('status', 'unknown')} "
        f"calibrated_by={calibration.get('calibrated_by', 'unknown')} "
        f"({calibration.get('pair_count', 0)} pairs)"
    )
    return "\n".join(lines)


def _build_report(
    *,
    mode: str,
    specs: list[AnswerSuiteSpec],
    safety_gate: dict[str, Any] | None,
    framework_runs: list[dict[str, Any]],
    calibration: dict[str, Any],
    alias: str | None,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "kind": "framework_answer_quality",
        "mode": mode,
        "alias": alias,
        "status": status,
        "error": error,
        "release_gate": None if safety_gate is None else release_gate(safety_gate),
        "safety_gate": safety_gate,
        "framework_runs": framework_runs,
        "calibration": calibration,
        "suite_names": [spec.name for spec in specs],
        "limitations": list(FRAMEWORK_LIMITATIONS),
    }
    return report


def _load_calibration_inputs(
    calibration_file: Path,
    reviewer_file: Path | None,
    judge_labels_file: Path | None,
) -> tuple[CalibrationSet, ReviewerLabels | None, dict[str, Any]]:
    calibration = load_calibration(calibration_file)
    reviewer = (
        load_reviewer_labels(reviewer_file, calibration) if reviewer_file is not None else None
    )
    judge = (
        load_judge_labels(judge_labels_file, calibration) if judge_labels_file is not None else None
    )
    return (
        calibration,
        reviewer,
        build_calibration_artifact(calibration, reviewer=reviewer, judge=judge),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        default="rag_w3",
        choices=["rag_w3", "qa_x01", "all"],
        help="Answer-bearing suite to select (default rag_w3)",
    )
    parser.add_argument(
        "--framework",
        default="auto",
        choices=["auto", "ragas", "deepeval"],
        help="Framework adapter; auto follows the selected suite",
    )
    parser.add_argument("--alias", default="judge", help="LiteLLM judge alias or model purpose")
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Validate fixtures and run the deterministic safety gate; make no model calls",
    )
    parser.add_argument(
        "--calibration-only",
        action="store_true",
        help="Write the judge-calibration artefact without running any suite",
    )
    parser.add_argument(
        "--calibration-file",
        type=Path,
        default=CALIBRATION_PATH,
        help="Paired good/bad calibration dataset",
    )
    parser.add_argument(
        "--reviewer-file",
        type=Path,
        help="Completed human-review labels; without it calibration stays pending",
    )
    parser.add_argument(
        "--judge-labels",
        type=Path,
        help="Optional externally produced judge verdicts for judge-vs-human agreement",
    )
    parser.add_argument("--report", type=Path, help="Write the full JSON report to this path")
    parser.add_argument(
        "--calibration-out",
        type=Path,
        default=DEFAULT_CALIBRATION_OUT,
        help="Judge-calibration artefact path (default evals/reports/judge_calibration.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress the human summary")
    args = parser.parse_args(argv)

    if args.no_judge and args.calibration_only:
        print("error: --no-judge and --calibration-only are mutually exclusive", file=sys.stderr)
        return 2

    try:
        specs = _selected_specs(args.suite, args.framework)
        _calibration, _reviewer, calibration_artifact = _load_calibration_inputs(
            args.calibration_file, args.reviewer_file, args.judge_labels
        )
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.calibration_only:
        try:
            write_calibration_artifact(args.calibration_out, calibration_artifact)
        except OSError as exc:
            print(f"error: cannot write calibration artefact: {exc}", file=sys.stderr)
            return 2
        report = _build_report(
            mode="calibration_only",
            specs=specs,
            safety_gate=None,
            framework_runs=[],
            calibration=calibration_artifact,
            alias=None,
            status=str(calibration_artifact["status"]),
        )
        _write_json(args.report, report)
        if not args.quiet:
            print(_summary(report), file=sys.stderr)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    try:
        suites = load_answer_suites([spec.name for spec in specs])
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        safety_gate = run_safety_gate()
    except EvalError as exc:
        print(f"error: deterministic safety gate failed to load: {exc}", file=sys.stderr)
        return 2

    if args.no_judge:
        framework_runs = [_suite_metadata(suite) for suite in suites]
        for run in framework_runs:
            run["status"] = "not_run"
            run["error"] = "--no-judge: no framework adapter was invoked and no score exists"
        gate = release_gate(safety_gate)
        status = "blocked" if gate["status"] == "blocked" else "not_run"
        report = _build_report(
            mode="no_judge",
            specs=specs,
            safety_gate=safety_gate,
            framework_runs=framework_runs,
            calibration=calibration_artifact,
            alias=None,
            status=status,
        )
        try:
            write_calibration_artifact(args.calibration_out, calibration_artifact)
        except OSError as exc:
            print(f"error: cannot write calibration artefact: {exc}", file=sys.stderr)
            return 2
        _write_json(args.report, report)
        if not args.quiet:
            print(_summary(report), file=sys.stderr)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if status == "blocked" else 0

    missing = _missing_judge_env()
    if missing:
        message = (
            "model-dependent framework run skipped because required environment is not set: "
            f"{', '.join(missing)}; export the LiteLLM variables or use --no-judge to "
            "validate fixtures offline"
        )
        framework_runs = [
            {**_suite_metadata(suite), "status": "unavailable", "error": message}
            for suite in suites
        ]
        report = _build_report(
            mode="judge",
            specs=specs,
            safety_gate=safety_gate,
            framework_runs=framework_runs,
            calibration=calibration_artifact,
            alias=args.alias,
            status="unavailable",
            error=message,
        )
        try:
            write_calibration_artifact(args.calibration_out, calibration_artifact)
        except OSError as exc:
            print(f"error: cannot write calibration artefact: {exc}", file=sys.stderr)
            return 2
        _write_json(args.report, report)
        if not args.quiet:
            print(_summary(report), file=sys.stderr)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 3

    try:
        judge_alias = resolve_alias(args.alias)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    framework_runs = [_run_suite(suite, judge_alias=judge_alias) for suite in suites]
    gate = release_gate(safety_gate)
    if gate["status"] == "blocked":
        status = "blocked"
        exit_code = 1
    elif any(run["status"] == "unavailable" for run in framework_runs):
        status = "unavailable"
        exit_code = 3
    elif any(run["status"] == "error" for run in framework_runs):
        status = "error"
        exit_code = 1
    else:
        status = "scored"
        exit_code = 0

    report = _build_report(
        mode="judge",
        specs=specs,
        safety_gate=safety_gate,
        framework_runs=framework_runs,
        calibration=calibration_artifact,
        alias=judge_alias,
        status=status,
    )
    try:
        write_calibration_artifact(args.calibration_out, calibration_artifact)
    except OSError as exc:
        print(f"error: cannot write calibration artefact: {exc}", file=sys.stderr)
        return 2
    _write_json(args.report, report)
    if not args.quiet:
        print(_summary(report), file=sys.stderr)
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
