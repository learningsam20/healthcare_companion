#!/usr/bin/env python3
"""G-13: ingest clinician grades for LIVE X-01 drafts and report acceptance.

Input is the draft artefact from ``nursing_x01_live.py`` plus the completed CSV. The
report's ``status`` is only ``graded_pass``/``graded_fail`` when every counted row
references a live draft, carries a named grader who set ``grader_attested=true`` and
the full 20-case set is covered. Anything else is ``incomplete``/``invalid`` and the
report states ``closes_gap: false``. This tool cannot verify a grader's identity or
credentials; G-13 closure still needs a human sign-off recorded in docs/gaps.md.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CASES = 20
DECISIONS = {"accept", "edit", "reject"}
TRUTHY = {"true", "yes", "y", "1"}
MIN_ACCURACY = 4.0
MIN_ACCEPTABLE_RATE = 0.8


def _score(value: str) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 1 <= number <= 5 else None


def evaluate(
    drafts_artefact: dict[str, Any],
    rows: list[dict[str, str]],
    *,
    required_cases: int = REQUIRED_CASES,
) -> dict[str, Any]:
    errors: list[str] = []
    if drafts_artefact.get("kind") != "nursing_x01_live_drafts" or not drafts_artefact.get("live"):
        errors.append("drafts_artefact_not_live_nursing_x01")
    live = {str(d["summary_id"]): d for d in drafts_artefact.get("drafts", []) if "summary_id" in d}
    graded: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=2):  # header is line 1
        case_id = (row.get("case_id") or "").strip()
        summary_id = (row.get("summary_id") or "").strip()
        where = f"line {index} ({case_id or 'no case_id'})"
        if summary_id not in live or live[summary_id]["case_id"] != case_id:
            errors.append(f"{where}: summary_id not a live draft for this case")
            continue
        grader = (row.get("grader_id") or "").strip()
        if not grader:
            errors.append(f"{where}: grader_id required")
            continue
        if (row.get("grader_attested") or "").strip().lower() not in TRUTHY:
            errors.append(f"{where}: grader_attested must be true")
            continue
        accuracy = _score(row.get("accuracy_1_5", ""))
        citation = _score(row.get("citation_support_1_5", ""))
        decision = (row.get("clinically_acceptable") or "").strip().lower()
        invented = (row.get("invented_content") or "").strip().lower()
        if accuracy is None or citation is None:
            errors.append(f"{where}: accuracy_1_5 and citation_support_1_5 must be 1-5")
            continue
        if decision not in DECISIONS:
            errors.append(f"{where}: clinically_acceptable must be accept|edit|reject")
            continue
        if invented not in {"yes", "no", "true", "false"}:
            errors.append(f"{where}: invented_content must be yes|no")
            continue
        if case_id in graded:
            errors.append(f"{where}: duplicate grade for case")
            continue
        graded[case_id] = {
            "grader_id": grader,
            "grader_role": (row.get("grader_role") or "").strip(),
            "accuracy": accuracy,
            "citation_support": citation,
            "decision": decision,
            "invented": invented in {"yes", "true"},
        }

    n = len(graded)
    acceptable = sum(1 for g in graded.values() if g["decision"] in {"accept", "edit"})
    invented_count = sum(1 for g in graded.values() if g["invented"])
    mean_accuracy = round(sum(g["accuracy"] for g in graded.values()) / n, 2) if n else None
    mean_citation = round(sum(g["citation_support"] for g in graded.values()) / n, 2) if n else None
    rate = round(acceptable / n, 3) if n else None
    graders = sorted({g["grader_id"] for g in graded.values()})

    if errors:
        status = "invalid"
    elif n < required_cases:
        status = "incomplete"
    elif (
        invented_count == 0
        and mean_accuracy is not None
        and mean_accuracy >= MIN_ACCURACY
        and rate is not None
        and rate >= MIN_ACCEPTABLE_RATE
    ):
        status = "graded_pass"
    else:
        status = "graded_fail"
    return {
        "kind": "nursing_x01_clinical_grades",
        "status": status,
        "required_cases": required_cases,
        "graded_cases": n,
        "graders": graders,
        "acceptable_rate": rate,
        "mean_accuracy": mean_accuracy,
        "mean_citation_support": mean_citation,
        "invented_content_cases": invented_count,
        "thresholds": {
            "min_mean_accuracy": MIN_ACCURACY,
            "min_acceptable_rate": MIN_ACCEPTABLE_RATE,
            "invented_content_allowed": 0,
        },
        "errors": errors,
        "closes_gap": False,
        "note": (
            "Evidence input for G-13 only. This tool cannot verify grader identity or "
            "clinical credentials; closure needs a named clinical sign-off in docs/gaps.md."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drafts", type=Path, required=True, help="nursing-x01-live-*.json")
    parser.add_argument("--grades", type=Path, required=True, help="completed grade CSV")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    artefact = json.loads(args.drafts.read_text(encoding="utf-8"))
    with args.grades.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report = evaluate(artefact, rows)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["status"] == "graded_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
