"""G-28 Hinglish/PHI fixture shape + regex-path expectations (composite when weights exist)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "evals" / "fixtures" / "pii_hinglish_phi.json"

PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.\w[\w.-]*\b"),
    "phone_in": re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)"),
    "aadhaar": re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "pan": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "mrn": re.compile(r"\bMRN[\s:-]*\d{4,12}\b", re.IGNORECASE),
}


def test_pii_fixture_regex_expectations() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["synthetic"] is True
    for case in payload["cases"]:
        found = {name for name, pattern in PATTERNS.items() if pattern.search(case["text"])}
        for expected in case["expect_types"]:
            if expected in PATTERNS:
                assert expected in found, f"{case['id']} missing {expected}"


def test_nursing_x01_eval_has_twenty_cases() -> None:
    path = ROOT / "evals" / "sets" / "nursing_x01.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 20
    assert all(row.get("must_cite") for row in rows)
    assert {row["decision"] for row in rows} >= {"accept", "edit", "reject"}
