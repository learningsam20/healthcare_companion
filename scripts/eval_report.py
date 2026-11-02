#!/usr/bin/env python3
"""Render an eval runner JSON report as Markdown evidence.

Also surfaces G-01/G-02 clinical i18n sign-off when
`docs/evidence/i18n-safety-key-audit.json` is present (from
`scripts/i18n_safety_key_audit.py`), so an approver signature is visible in
the eval/handover report pack — not only in a side file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_I18N_AUDIT = ROOT / "docs" / "evidence" / "i18n-safety-key-audit.json"


def _metric_cell(metrics: dict[str, Any]) -> str:
    if not metrics:
        return "—"
    return ", ".join(f"{key}={float(value):.3f}" for key, value in sorted(metrics.items()))


def _i18n_signoff_section(audit_path: Path | None) -> list[str]:
    lines = [
        "## G-01 / G-02 — Clinical i18n sign-off",
        "",
    ]
    if audit_path is None or not audit_path.exists():
        lines.extend(
            [
                "Status: **unreviewed** (no `i18n-safety-key-audit.json`).",
                "Run `scripts/i18n_safety_key_audit.py` after recording "
                "`docs/evidence/i18n-clinical-signoff.json`.",
                "",
            ]
        )
        return lines
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        lines.extend([f"Status: **unreviewed** (audit unreadable: {exc}).", ""])
        return lines
    review = audit.get("clinical_review") if isinstance(audit, dict) else None
    if not isinstance(review, dict):
        review = {"review_status": audit.get("review_status", "unreviewed") if isinstance(audit, dict) else "unreviewed"}
    status = str(review.get("review_status") or audit.get("review_status") or "unreviewed")
    lines.append(f"- Review status: **{status}**")
    if status == "approved":
        lines.extend(
            [
                f"- Approver: **{review.get('approver_name')}**"
                + (f" ({review.get('approver_role')})" if review.get("approver_role") else ""),
                f"- Signed at: `{review.get('signed_at')}`",
                f"- Clinical report: [clinical-i18n-report.md](./clinical-i18n-report.md)",
                f"- Audit JSON: [{audit_path.name}](./{audit_path.name})",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "- Approver: — (not signed)",
                f"- Detail: {review.get('note') or audit.get('note') or 'unreviewed'}",
                f"- Clinical report: [clinical-i18n-report.md](./clinical-i18n-report.md)",
                "",
                "Hi/mr safety copy is **not** claimed as clinically validated until status is approved.",
                "",
            ]
        )
    return lines


def render(report: dict[str, Any], *, i18n_audit: Path | None = DEFAULT_I18N_AUDIT) -> str:
    lines = [
        "# Evaluation report",
        "",
        f"- Run: `{report.get('run_id', 'unknown')}`",
        f"- Created: {report.get('created_at', 'unknown')}",
        f"- Status: **{report.get('status', 'unknown')}**",
        f"- Framework requested: `{report.get('framework', 'unknown')}`",
        f"- Judge alias: `{report.get('alias', 'unknown')}`",
        f"- Stub: {report.get('stub', False)}",
        "",
    ]
    runs = report.get("runs") or []
    if runs:
        lines.extend(
            [
                "| Suite | Framework | Version | Status | Cases | Metrics |",
                "|---|---|---|---|---|---|",
            ]
        )
        for run in runs:
            lines.append(
                (
                    "| {suite} | {framework} | {version} | {status} | "
                    "{passed}/{total} | {metrics} |"
                ).format(
                    suite=run.get("suite", ""),
                    framework=run.get("framework", ""),
                    version=run.get("framework_version", ""),
                    status=run.get("status", ""),
                    passed=run.get("passed_cases", 0),
                    total=run.get("case_count", 0),
                    metrics=_metric_cell(run.get("metrics") or {}),
                )
            )
        lines.append("")
    else:
        lines.extend(["No suites ran.", ""])

    failures = [
        (run.get("suite", ""), case)
        for run in runs
        for case in run.get("cases") or []
        if not case.get("passed")
    ]
    if failures:
        lines.extend(["## Failing cases", ""])
        for suite, case in failures:
            detail = "; ".join(case.get("failures") or [])
            lines.append(f"- `{suite}` `{case.get('id', 'unknown')}` — {detail}")
        lines.append("")

    if report.get("error"):
        lines.extend(["## Error", "", str(report["error"]), ""])

    lines.extend(_i18n_signoff_section(i18n_audit))
    lines.extend(
        [
            "Deterministic safety failures are release blockers. RAGAS/DeepEval scores "
            "cannot overrule a failed red-flag, provenance or citation case.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="JSON report from the eval runner")
    parser.add_argument("output", type=Path, help="Markdown path to write")
    parser.add_argument(
        "--i18n-audit",
        type=Path,
        default=DEFAULT_I18N_AUDIT,
        help="G-01/G-02 audit JSON to embed (sign-off visibility)",
    )
    parser.add_argument(
        "--no-i18n-audit",
        action="store_true",
        help="Omit the clinical i18n sign-off section",
    )
    args = parser.parse_args()
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read eval report: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("error: eval report must be a JSON object", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    audit = None if args.no_i18n_audit else args.i18n_audit
    args.output.write_text(render(payload, i18n_audit=audit), encoding="utf-8")
    print(f"report written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
