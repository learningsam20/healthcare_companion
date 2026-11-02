#!/usr/bin/env python3
"""G-13: generate LIVE X-01 nursing drafts through the API and emit a clinician grade sheet.

This harness calls ``POST /api/v1/nursing/summary`` for each intent in
``evals/sets/nursing_x01.jsonl`` against a running stack (flag ``x01_nursing_summary``
must be on). It records the drafts and writes a CSV template for a named clinician to
grade. It does **not** score clinical quality and never fabricates a draft: if the API
is unreachable or the flag is off, the case is recorded as an error and the run is not
usable as grading input.

Next step: ``evals/harness/nursing_x01_grades.py`` ingests the completed CSV.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = ROOT / "evals" / "sets" / "nursing_x01.jsonl"
DEFAULT_PATIENT_ID = "20000000-0000-4000-8000-000000000001"  # synthetic demo patient (Priya)
GRADE_COLUMNS = [
    "case_id",
    "summary_id",
    "grader_id",
    "grader_role",
    "grader_attested",
    "accuracy_1_5",
    "citation_support_1_5",
    "invented_content",
    "clinically_acceptable",
    "notes",
]
ARTEFACT_KIND = "nursing_x01_live_drafts"


class Poster(Protocol):
    def post(self, path: str, body: dict[str, Any], *, username: str) -> Any: ...


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


def generate_draft(
    client: Poster, case: dict[str, Any], *, patient_id: str, username: str
) -> dict[str, Any]:
    """Call the live API for one intent. Errors are recorded, never replaced by a mock."""
    row: dict[str, Any] = {
        "case_id": case["id"],
        "question": case["question"],
        "language": case.get("language", "en-IN"),
    }
    try:
        response = client.post(
            "/api/v1/nursing/summary",
            {
                "patient_id": patient_id,
                "query": case["question"],
                "locale": case.get("language", "en-IN"),
            },
            username=username,
        )
    except Exception as exc:  # noqa: BLE001 - recorded verbatim; run is then unusable
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return row
    if not isinstance(response, dict) or not response.get("id"):
        row["error"] = "malformed_response"
        return row
    row.update(
        {
            "summary_id": response["id"],
            "version": response.get("version"),
            "status": response.get("status"),
            "summary": response.get("summary", ""),
            "source_count": len(response.get("sources") or []),
            "graph": response.get("graph"),
            "model_alias": response.get("model_alias"),
        }
    )
    return row


def build_artefact(
    drafts: list[dict[str, Any]], *, patient_id: str, username: str, base_url: str
) -> dict[str, Any]:
    ok = [row for row in drafts if "summary_id" in row]
    return {
        "kind": ARTEFACT_KIND,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "api_base_url": base_url,
        "patient_id": patient_id,
        "requested_as": username,
        "live": True,
        "total_cases": len(drafts),
        "generated": len(ok),
        "errors": len(drafts) - len(ok),
        "clinical_quality_scored": False,
        "drafts": drafts,
        "limitations": [
            "Drafts only; no clinical quality score exists until a named clinician grades them.",
            "Demo patient data is synthetic; this is not a real-patient clinical evaluation.",
        ],
    }


def write_grade_template(path: Path, drafts: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GRADE_COLUMNS)
        writer.writeheader()
        for row in drafts:
            if "summary_id" not in row:
                continue
            writer.writerow({"case_id": row["case_id"], "summary_id": row["summary_id"]})
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--patient-id", default=DEFAULT_PATIENT_ID)
    parser.add_argument("--username", default="doctor.rao", help="Keycloak user to draft as")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N cases (0 = all)")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "docs" / "evidence" / f"nursing-x01-live-{stamp}.json"
    )
    parser.add_argument(
        "--grades-template",
        type=Path,
        default=ROOT / "evals" / "reports" / f"nursing-x01-grades-{stamp}.csv",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "scripts"))
    from ops_client import OpsClient, OpsError

    cases = load_cases(args.fixture)
    if args.limit:
        cases = cases[: args.limit]
    client = OpsClient()
    drafts: list[dict[str, Any]] = []
    for case in cases:
        try:
            drafts.append(
                generate_draft(client, case, patient_id=args.patient_id, username=args.username)
            )
        except OpsError as exc:  # pragma: no cover - auth failure aborts the whole run
            print(f"error: {exc}", file=sys.stderr)
            return 2
    artefact = build_artefact(
        drafts, patient_id=args.patient_id, username=args.username, base_url=client.api
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artefact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = write_grade_template(args.grades_template, drafts)
    print(
        json.dumps(
            {
                "artefact": str(args.out),
                "grades_template": str(args.grades_template),
                "generated": artefact["generated"],
                "errors": artefact["errors"],
                "grade_rows": rows,
            },
            indent=2,
        )
    )
    return 0 if artefact["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
