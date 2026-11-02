#!/usr/bin/env python3
"""Deterministic evaluation harness and optional RAGAS/DeepEval adapter runner.

The deterministic safety gate runs offline against the approved rule and provenance
configuration. RAGAS and DeepEval adapters are optional: when their dependencies are
not installed the run is recorded as ``unavailable`` and the command exits non-zero.
Framework scores can never turn a failed deterministic safety case into a pass.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import importlib
import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))

import yaml  # noqa: E402
from sahyog_common.provenance import (  # noqa: E402
    SourceRef,
    SourceType,
    forbidden_or_missing,
    has_usable_evidence,
    resolve_sources,
)
from sahyog_common.red_flags import (  # noqa: E402
    detect_red_flags,
    red_flag_sources,
)

from evals.harness.errors import AdapterUnavailable, EvalError  # noqa: E402

SETS_DIR = ROOT / "evals" / "sets"
AVAILABLE_SUITES = ("w1", "w2", "w3", "x01")
# Deterministic safety suites. Framework answer-quality scores are never part of this
# gate and can never turn a failed safety case into a pass.
SAFETY_SUITES = ("w1", "w2")
PATIENT_IDS = {
    "same": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "other": uuid.UUID("22222222-2222-4222-8222-222222222222"),
}
THRESHOLDS: dict[str, float] = {
    "case_pass_rate": 1.0,
    "red_flag_recall": 1.0,
    "red_flag_false_positive_rate": 0.0,
    "provenance_integrity": 1.0,
}


@dataclass
class SuiteResult:
    suite: str
    framework: str
    framework_version: str
    dataset_hash: str
    cases: list[dict[str, Any]]
    metrics: dict[str, float] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=lambda: dict(THRESHOLDS))
    error: str | None = None

    @property
    def passed_cases(self) -> int:
        return sum(1 for case in self.cases if case["passed"])

    @property
    def failed_cases(self) -> int:
        return len(self.cases) - self.passed_cases

    @property
    def status(self) -> str:
        if self.error is not None:
            return "unavailable"
        case_pass_rate = self.metrics.get("case_pass_rate", 0.0)
        failed_threshold = any(
            self.metrics.get(key, 0.0) < threshold
            if key != "red_flag_false_positive_rate"
            else self.metrics.get(key, 1.0) > threshold
            for key, threshold in self.thresholds.items()
            if key in self.metrics
        )
        if self.failed_cases or case_pass_rate < 1.0 or failed_threshold:
            return "failed"
        return "passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "framework": self.framework,
            "framework_version": self.framework_version,
            "status": self.status,
            "dataset_hash": self.dataset_hash,
            "case_count": len(self.cases),
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "cases": self.cases,
            "error": self.error,
        }


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise EvalError(f"{path} must contain a YAML object")
    return data


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_sha() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - fixed command, no user input
            [git, "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _versioning() -> dict[str, str | None]:
    prompts = list((ROOT / "config" / "prompts").glob("*.yaml"))
    agents = list((ROOT / "apps" / "api" / "app" / "agents").glob("*.py"))
    return {
        "prompt_version": _combined_hash(prompts)[:16] if prompts else None,
        "graph_version": _combined_hash(agents)[:16] if agents else None,
        "git_sha": _git_sha(),
    }


def _load_cases(suite: str) -> tuple[list[dict[str, Any]], str]:
    path = SETS_DIR / f"{suite}.jsonl"
    if not path.exists():
        raise EvalError(
            f"suite {suite} has no case set at {path.relative_to(ROOT)}; "
            "available: " + ", ".join(_available_suites())
        )
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalError(f"{path.name}:{number} is not valid JSON: {exc}") from exc
        if not isinstance(case, dict) or "id" not in case or "check" not in case:
            raise EvalError(f"{path.name}:{number} needs id and check")
        if case["id"] in seen:
            raise EvalError(f"{path.name}:{number} repeats case id {case['id']}")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise EvalError(f"suite {suite} has no cases")
    return cases, _hash_file(path)


def _available_suites() -> list[str]:
    return [suite for suite in AVAILABLE_SUITES if (SETS_DIR / f"{suite}.jsonl").exists()]


def _source_ref(ref: dict[str, Any], current_patient: uuid.UUID) -> SourceRef:
    patient_marker = ref.get("patient_id")
    if patient_marker == "same":
        patient_id = current_patient
    elif patient_marker == "other":
        patient_id = PATIENT_IDS["other"]
    elif patient_marker is None:
        patient_id = None
    else:
        raise EvalError(f"unknown patient_id token {patient_marker!r}")
    observed_at = (
        dt.datetime.fromisoformat(ref["observed_at"].replace("Z", "+00:00"))
        if ref.get("observed_at")
        else None
    )
    return SourceRef(
        id=str(ref["id"]),
        type=SourceType(str(ref["type"])),
        title=str(ref.get("title", ref["id"])),
        locator=ref.get("locator"),
        patient_id=patient_id,
        observed_at=observed_at,
        status=str(ref.get("claimed_status", "resolved")),
    )


def _check_red_flag(case: dict[str, Any], red_flag_config: dict[str, Any]) -> dict[str, Any]:
    language = str(case.get("language", "en-IN"))
    matches = detect_red_flags(str(case["input"]), red_flag_config, language)
    expected = [str(rule_id) for rule_id in case["expect"].get("rules", [])]
    actual = [match.rule_id for match in matches]
    failures: list[str] = []
    if actual != expected:
        failures.append(f"expected rules {expected}, got {actual}")
    expected_severity = case["expect"].get("severity")
    expected_action = case["expect"].get("action")
    for match in matches:
        if expected_severity and match.severity != expected_severity:
            failures.append(f"{match.rule_id} severity {match.severity} != {expected_severity}")
        if expected_action and match.action != expected_action:
            failures.append(f"{match.rule_id} action {match.action} != {expected_action}")
        if not match.guidance.strip():
            failures.append(f"{match.rule_id} has no safety guidance for {language}")
    if matches:
        resolved = resolve_sources(red_flag_sources(matches), current_patient_id=None)
        if forbidden_or_missing(resolved) or not has_usable_evidence(resolved):
            failures.append("red-flag rule sources are not usable evidence")
    return {
        "id": case["id"],
        "check": "red_flag",
        "language": language,
        "passed": not failures,
        "failures": failures,
        "actual_rules": actual,
    }


def _check_provenance(case: dict[str, Any]) -> dict[str, Any]:
    current_patient = PATIENT_IDS["same"]
    now = dt.datetime.fromisoformat(str(case.get("now", "2026-10-25T12:00:00+00:00")))
    refs = [_source_ref(ref, current_patient) for ref in case["sources"]]
    resolved = resolve_sources(refs, current_patient_id=current_patient, now=now)
    expect = case["expect"]
    actual_statuses = [ref.status.value for ref in resolved]
    actual_usable = [ref.usable_as_evidence for ref in resolved]
    failures: list[str] = []
    if actual_statuses != expect["statuses"]:
        failures.append(f"expected statuses {expect['statuses']}, got {actual_statuses}")
    if actual_usable != expect["usable"]:
        failures.append(f"expected usable {expect['usable']}, got {actual_usable}")
    expected_count = expect.get("count", len(expect["statuses"]))
    if len(resolved) != expected_count:
        failures.append(f"expected {expected_count} deduplicated refs, got {len(resolved)}")
    return {
        "id": case["id"],
        "check": "provenance",
        "passed": not failures,
        "failures": failures,
        "actual_statuses": actual_statuses,
    }


def _evaluate_cases(
    cases: list[dict[str, Any]], red_flag_config: dict[str, Any]
) -> list[dict[str, Any]]:
    results = []
    for case in cases:
        check = case["check"]
        if check == "red_flag":
            results.append(_check_red_flag(case, red_flag_config))
        elif check == "provenance":
            results.append(_check_provenance(case))
        else:
            results.append(
                {
                    "id": case["id"],
                    "check": check,
                    "passed": False,
                    "failures": [f"unknown check {check!r}"],
                }
            )
    return results


def _suite_metrics(
    suite: str, cases: list[dict[str, Any]], results: list[dict[str, Any]]
) -> dict[str, float]:
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    metrics = {"case_pass_rate": round(passed / total, 6) if total else 0.0}
    if suite == "w1":
        positives = [
            result
            for case, result in zip(cases, results, strict=True)
            if case["expect"].get("rules")
        ]
        negatives = [
            result
            for case, result in zip(cases, results, strict=True)
            if not case["expect"].get("rules")
        ]
        metrics["red_flag_recall"] = (
            round(sum(1 for result in positives if result["passed"]) / len(positives), 6)
            if positives
            else 0.0
        )
        metrics["red_flag_false_positive_rate"] = (
            round(sum(1 for result in negatives if not result["passed"]) / len(negatives), 6)
            if negatives
            else 0.0
        )
    if suite == "w2":
        metrics["provenance_integrity"] = metrics["case_pass_rate"]
    return metrics


def _run_deterministic(suite: str, cases: list[dict[str, Any]], dataset_hash: str) -> SuiteResult:
    config = _read_yaml(ROOT / "config" / "red_flags.yaml")
    results = _evaluate_cases(cases, config)
    metrics = _suite_metrics(suite, cases, results)
    thresholds = dict(THRESHOLDS)
    thresholds = {key: value for key, value in thresholds.items() if key in metrics}
    return SuiteResult(
        suite=suite,
        framework="deterministic",
        framework_version="1",
        dataset_hash=dataset_hash,
        cases=results,
        metrics=metrics,
        thresholds=thresholds,
    )


def run_deterministic_suite(suite: str) -> SuiteResult:
    """Run one deterministic suite offline. Public entry point for focused runners."""
    cases, dataset_hash = _load_cases(suite)
    return _run_deterministic(suite, cases, dataset_hash)


def run_safety_gate() -> dict[str, Any]:
    """Return the deterministic safety gate result used as the release blocker.

    This function intentionally ignores framework scores.  A focused framework runner
    can call it and must treat a non-passed result as blocking regardless of any
    RAGAS/DeepEval metric.
    """
    runs = [run_deterministic_suite(suite).to_dict() for suite in SAFETY_SUITES]
    failed_cases = sum(int(run["failed_cases"]) for run in runs)
    case_count = sum(int(run["case_count"]) for run in runs)
    passed = failed_cases == 0 and all(run["status"] == "passed" for run in runs)
    return {
        "status": "passed" if passed else "failed",
        "basis": "deterministic_red_flag_and_provenance",
        "framework_scores_used": False,
        "suites": runs,
        "case_count": case_count,
        "passed_cases": case_count - failed_cases,
        "failed_cases": failed_cases,
        "dataset_hashes": {run["suite"]: run["dataset_hash"] for run in runs},
    }


def _resolve_alias(purpose_or_alias: str) -> str:
    config = _read_yaml(ROOT / "config" / "models.yaml")
    aliases = config.get("aliases", {})
    purposes = config.get("purposes", {})
    if purpose_or_alias in aliases:
        return purpose_or_alias
    purpose = purposes.get(purpose_or_alias)
    if isinstance(purpose, dict) and purpose.get("primary") in aliases:
        return str(purpose["primary"])
    raise EvalError(f"{purpose_or_alias!r} is not a configured LiteLLM alias or model purpose")


def _adapter(framework: str) -> Any:
    module_name = f"evals.adapters.{framework}.adapter"
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise AdapterUnavailable(f"adapter {module_name} is not importable: {exc}") from exc


def resolve_alias(purpose_or_alias: str) -> str:
    """Resolve a model purpose or alias against config/models.yaml."""
    return _resolve_alias(purpose_or_alias)


def run_framework_adapter(
    framework: str, cases: list[dict[str, Any]], *, judge_alias: str
) -> dict[str, Any]:
    """Run an installed optional adapter. Public entry point for focused runners."""
    return _run_framework(framework, "", cases, judge_alias=judge_alias, stub=False)


def _run_framework(
    framework: str,
    suite: str,
    cases: list[dict[str, Any]],
    *,
    judge_alias: str,
    stub: bool,
) -> dict[str, Any]:
    if stub:
        raise EvalError("--stub is only valid with --framework deterministic")
    module = _adapter(framework)
    available = getattr(module, "run", None)
    if available is None:
        raise AdapterUnavailable(f"adapter {framework} has no run() entry point")
    try:
        version = metadata.version(framework)
    except metadata.PackageNotFoundError as exc:
        raise AdapterUnavailable(
            f"{framework} is not installed; install the optional eval dependencies "
            f"(uv sync --extra eval) before running this framework"
        ) from exc
    outcome = available(cases, judge_alias=judge_alias)
    if not isinstance(outcome, dict) or "metrics" not in outcome:
        raise EvalError(f"adapter {framework} returned an invalid result")
    return {
        "framework_version": version,
        "metrics": {str(key): float(value) for key, value in outcome["metrics"].items()},
        "cases": outcome.get("cases", []),
    }


async def _persist(
    results: list[SuiteResult], *, judge_alias: str | None, report: dict[str, Any]
) -> list[str | None]:
    from app.composition import build_app_services  # noqa: PLC0415
    from app.core.config import get_settings  # noqa: PLC0415
    from app.repositories.audit import AuditRepository  # noqa: PLC0415
    from app.repositories.models import EvalMetricResult, EvalRun  # noqa: PLC0415

    settings = get_settings()
    services = build_app_services(settings)
    artifact_keys: list[str | None] = []
    try:
        async with services.db.sessionmaker() as session:
            for result in results:
                versioning = _versioning()
                run = EvalRun(
                    suite=result.suite,
                    framework=result.framework,
                    framework_version=result.framework_version,
                    status=result.status,
                    dataset_hash=result.dataset_hash,
                    git_sha=versioning["git_sha"],
                    prompt_version=versioning["prompt_version"],
                    graph_version=versioning["graph_version"],
                    judge_alias=judge_alias if result.framework != "deterministic" else None,
                    case_count=len(result.cases),
                    passed_cases=result.passed_cases,
                    failed_cases=result.failed_cases,
                    metrics=result.metrics,
                    thresholds=result.thresholds,
                    case_results=result.cases,
                    error_message=result.error,
                )
                session.add(run)
                await session.flush()
                for metric_key, value in result.metrics.items():
                    session.add(
                        EvalMetricResult(
                            run_id=run.id,
                            metric_key=metric_key,
                            value=value,
                            unit="ratio",
                            framework=result.framework,
                            dimensions={"suite": result.suite, "dataset": result.dataset_hash},
                        )
                    )
                artifact_key = None
                if services.settings.s3_configured:
                    artifact_key = f"evals/{result.framework}/{result.suite}/{run.id}.json"
                    await services.storage.put(
                        key=artifact_key,
                        data=json.dumps(
                            {"report": report, "run": result.to_dict()},
                            indent=2,
                            sort_keys=True,
                        ).encode(),
                        content_type="application/json",
                        bucket=services.settings.s3_bucket_eval,
                    )
                    run.artifact_key = artifact_key
                artifact_keys.append(artifact_key)
                AuditRepository(session).append(
                    actor_subject="system:evals",
                    actor_role="admin",
                    action="eval.run_recorded",
                    resource_type="eval_run",
                    resource_id=str(run.id),
                    metadata={
                        "suite": result.suite,
                        "framework": result.framework,
                        "status": result.status,
                        "dataset_hash": result.dataset_hash,
                    },
                )
            await session.commit()
    finally:
        await services.db.dispose()
    return artifact_keys


def _summary(report: dict[str, Any]) -> str:
    lines = [
        f"run {report['run_id']} · {report['status']} · {report['created_at']}",
    ]
    for run in report["runs"]:
        metrics = ", ".join(f"{key}={value:.3f}" for key, value in run["metrics"].items())
        lines.append(
            f"  {run['suite']}/{run['framework']}: {run['status']} "
            f"({run['passed_cases']}/{run['case_count']}) {metrics}"
        )
    if report.get("error"):
        lines.append(f"  error: {report['error']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="w1", choices=[*AVAILABLE_SUITES, "all"])
    parser.add_argument(
        "--framework",
        default="deterministic",
        choices=["deterministic", "ragas", "deepeval"],
    )
    parser.add_argument("--alias", default="judge", help="Judge alias routed through LiteLLM")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Prove the harness offline; only valid with the deterministic framework",
    )
    parser.add_argument("--no-persist", action="store_true", help="Do not write Postgres")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this path")
    parser.add_argument("--quiet", action="store_true", help="Suppress the human summary")
    args = parser.parse_args()

    if args.stub and args.framework != "deterministic":
        print("error: --stub only supports --framework deterministic", file=sys.stderr)
        return 2

    available = _available_suites()
    if args.suite == "all":
        suites = available
        if not suites:
            print("error: no approved eval case sets are present", file=sys.stderr)
            return 2
    else:
        if args.suite not in available:
            print(
                f"error: suite {args.suite} has no approved case set; "
                f"available: {', '.join(available) or 'none'}",
                file=sys.stderr,
            )
            return 2
        suites = [args.suite]

    try:
        judge_alias = _resolve_alias(args.alias)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    created_at = dt.datetime.now(dt.UTC)
    report: dict[str, Any] = {
        "run_id": str(uuid.uuid4()),
        "created_at": created_at.isoformat(),
        "framework": args.framework,
        "alias": judge_alias,
        "stub": args.stub,
        "status": "passed",
        "runs": [],
        "error": None,
    }
    results: list[SuiteResult] = []
    try:
        for suite in suites:
            cases, dataset_hash = _load_cases(suite)
            if args.framework == "deterministic" or args.stub:
                result = _run_deterministic(suite, cases, dataset_hash)
            else:
                result = _run_deterministic(suite, cases, dataset_hash)
                try:
                    adapter_result = _run_framework(
                        args.framework,
                        suite,
                        cases,
                        judge_alias=judge_alias,
                        stub=args.stub,
                    )
                    result.framework = args.framework
                    result.framework_version = str(adapter_result["framework_version"])
                    result.metrics.update(adapter_result["metrics"])
                    if adapter_result["cases"]:
                        result.cases.extend(adapter_result["cases"])
                except AdapterUnavailable as exc:
                    result.framework = args.framework
                    result.framework_version = "unavailable"
                    result.error = str(exc)
            results.append(result)
    except EvalError as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        print(json.dumps(report, indent=2, sort_keys=True), file=sys.stdout)
        return 2

    report["runs"] = [result.to_dict() for result in results]
    if any(result.status == "unavailable" for result in results):
        report["status"] = "unavailable"
        report["error"] = next(result.error for result in results if result.status == "unavailable")
    elif any(result.status == "failed" for result in results):
        report["status"] = "failed"

    if not args.no_persist:
        try:
            artifact_keys = asyncio.run(_persist(results, judge_alias=judge_alias, report=report))
            report["artifact_keys"] = artifact_keys
        except Exception as exc:  # the report must still be produced
            report["status"] = "error"
            report["error"] = f"could not persist the eval run: {exc}"
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            print(json.dumps(report, indent=2, sort_keys=True), file=sys.stdout)
            return 2

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if not args.quiet:
        print(_summary(report), file=sys.stderr)
    print(json.dumps(report, indent=2, sort_keys=True), file=sys.stdout)
    if report["status"] == "passed":
        return 0
    if report["status"] == "unavailable":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
