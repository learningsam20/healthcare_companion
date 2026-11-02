"""G-13 nursing X-01 draft eval: intent shape + optional citation structure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate_case(case: dict) -> list[str]:
    errors: list[str] = []
    if "draft" in case or "lines" in case:
        draft = case.get("draft") or {}
        lines = draft.get("lines") or case.get("lines") or []
        expect_refuse = bool(case.get("expect_refuse") or case.get("empty_evidence"))
        if expect_refuse:
            if lines:
                errors.append("expected_refuse_but_has_lines")
            return errors
        if not lines:
            errors.append("missing_lines")
            return errors
        for idx, line in enumerate(lines):
            cites = line.get("citations") or line.get("source_refs") or []
            if not cites:
                errors.append(f"line_{idx}_missing_citation")
            text = (line.get("text") or line.get("content") or "").strip()
            if not text:
                errors.append(f"line_{idx}_empty_text")
        return errors
    # Intent-only fixtures (evals/sets/nursing_x01.jsonl)
    if not case.get("id"):
        errors.append("missing_id")
    if case.get("must_cite") is not True:
        errors.append("must_cite_required")
    if case.get("must_not_invent") is not True:
        errors.append("must_not_invent_required")
    if case.get("decision") not in {"accept", "edit", "reject"}:
        errors.append("invalid_decision")
    if not (case.get("question") or "").strip():
        errors.append("missing_question")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("evals/sets/nursing_x01.jsonl"),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.fixture.exists():
        report = {
            "status": "scaffolding",
            "note": f"missing fixture {args.fixture}",
            "cases": [],
        }
        text = json.dumps(report, indent=2) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        print(text)
        return 0
    cases = []
    failures = []
    for line in args.fixture.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        errs = validate_case(case)
        row = {"id": case.get("id"), "ok": not errs, "errors": errs}
        cases.append(row)
        if errs:
            failures.append(case.get("id"))
    report = {
        "dataset": "nursing_x01",
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "cases": cases,
        "limitations": [
            "Intent/citation shape checks only; clinical quality not scored.",
            "Live model drafts are not exercised by this harness.",
        ],
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
