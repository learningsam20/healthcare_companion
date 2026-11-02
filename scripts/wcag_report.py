#!/usr/bin/env python3
"""G-36: generate ``docs/evidence/wcag_report.md`` honestly from real inputs.

Inputs (nothing is invented):
  * axe scan records written by the Playwright suite to
    ``apps/web/test-results/axe-scans/*.json`` (run ``scripts/test.sh --e2e``).
  * ``docs/evidence/a11y-manual-checklist.md`` (manual QA worksheet statuses).
  * optional ``docs/evidence/wcag-signoff.json`` (human QA sign-off).

The report states **"WCAG 2.2 AA conformance: NOT CLAIMED"** unless *every* checklist
row is ``Pass`` or ``N/A`` *and* a sign-off file with tester, date, build, browser and
screen-reader fields exists. Automated axe results alone can never produce a claim
(axe finds only a subset of WCAG issues, and covers WCAG 2.0/2.1 tags here, not 2.2).

Usage:
  uv run python scripts/wcag_report.py            # write docs/evidence/wcag_report.md
  uv run python scripts/wcag_report.py --check    # exit 1 if no axe scans were found
  uv run python scripts/wcag_report.py --out PATH --scans DIR

Exit codes: 0 report written; 1 ``--check`` and no scans; 2 usage / unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCANS = ROOT / "apps" / "web" / "test-results" / "axe-scans"
DEFAULT_CHECKLIST = ROOT / "docs" / "evidence" / "a11y-manual-checklist.md"
DEFAULT_SIGNOFF = ROOT / "docs" / "evidence" / "wcag-signoff.json"
DEFAULT_OUT = ROOT / "docs" / "evidence" / "wcag_report.md"
SIGNOFF_FIELDS = ("tester", "date", "build", "browser", "screen_reader")
KNOWN_STATUS = {"pass", "fail", "n/a", "eng only", ""}


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def load_scans(directory: Path) -> list[dict[str, Any]]:
    scans: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            scans.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"warning: skipping unreadable scan {path.name}: {exc}", file=sys.stderr)
    return scans


def parse_checklist(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] in {"Area", ""} or set(cells[0]) <= {"-"}:
            continue
        rows.append(
            {
                "area": cells[0],
                "check": cells[1],
                "criteria": cells[2],
                "status": cells[3],
                "evidence": cells[4],
            }
        )
    return rows


def load_signoff(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.is_file():
        return None, ["no sign-off file"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, [f"sign-off unreadable: {exc}"]
    missing = [f for f in SIGNOFF_FIELDS if not str(data.get(f) or "").strip()]
    return data, [f"sign-off missing field: {f}" for f in missing]


def conformance(
    rows: list[dict[str, str]], signoff: dict[str, Any] | None, signoff_problems: list[str]
) -> tuple[bool, list[str]]:
    """Return (claim_allowed, reasons_blocking)."""
    reasons: list[str] = []
    if not rows:
        reasons.append("manual checklist not found or empty")
    pending = [r for r in rows if r["status"].strip().lower() not in {"pass", "n/a"}]
    if pending:
        reasons.append(f"{len(pending)} of {len(rows)} checklist rows are not Pass/N/A")
    if signoff is None or signoff_problems:
        reasons.extend(signoff_problems or ["no sign-off file"])
    return not reasons, reasons


def render(
    scans: list[dict[str, Any]],
    rows: list[dict[str, str]],
    signoff: dict[str, Any] | None,
    signoff_problems: list[str],
    scans_dir: Path,
) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    allowed, reasons = conformance(rows, signoff, signoff_problems)
    status_counts = Counter((r["status"].strip() or "(blank)") for r in rows)
    blocking_scans = [s for s in scans if s.get("seriousOrCriticalCount", 0) > 0]
    rule_counts: Counter[str] = Counter()
    for scan in scans:
        for violation in scan.get("violations", []):
            rule_counts[f"{violation['id']} [{violation.get('impact')}]"] += 1
    axe_versions = sorted({str(s.get("axeVersion")) for s in scans if s.get("axeVersion")})
    scanned_at = sorted(str(s.get("scannedAt")) for s in scans if s.get("scannedAt"))

    out = [
        "# WCAG report",
        "",
        f"_Generated {now} by `scripts/wcag_report.py`. Inputs: axe scan records, manual "
        "checklist and optional sign-off. Nothing here is hand-written evidence._",
        "",
        "## Conformance statement",
        "",
    ]
    if allowed:
        out += [
            "**Internal checklist sign-off recorded** (every manual row Pass/N/A and a "
            "sign-off file present). This is an internal QA statement for the tested "
            "builds/browsers, **not** a third-party audit or legal certification.",
            "",
            f"- Tester: {signoff.get('tester') if signoff else ''}; "
            f"date: {signoff.get('date') if signoff else ''}; "
            f"build: {signoff.get('build') if signoff else ''}",
            f"- Browser: {signoff.get('browser') if signoff else ''}; "
            f"screen reader: {signoff.get('screen_reader') if signoff else ''}",
        ]
    else:
        out += [
            "**WCAG 2.2 AA conformance: NOT CLAIMED.** This app is **not AA certified**.",
            "",
            "Blocking reasons:",
            "",
            *[f"- {r}" for r in reasons],
        ]
    out += [
        "",
        "## Automated axe scans (Chromium, Playwright)",
        "",
        "Tags scanned: `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`. axe detects only a "
        "subset of WCAG failures and does not cover the 2.2-only criteria "
        "(e.g. 2.4.11 focus appearance, 2.5.8 target size) - a clean scan is **not** "
        "conformance.",
        "",
    ]
    if not scans:
        out += [
            f"**No axe scan records found** in `{_rel(scans_dir)}`. Run the e2e suite against the "
            "Compose stack (`scripts/test.sh --e2e`) and re-run this script. "
            "No scan results are reported or implied.",
            "",
        ]
    else:
        out += [
            f"- Scans: {len(scans)}; scans with serious/critical violations: {len(blocking_scans)}",
            f"- axe-core version(s): {', '.join(axe_versions) or 'unknown'}",
            f"- Scan window: {scanned_at[0]} .. {scanned_at[-1]}" if scanned_at else "",
            "",
            "| Project | Page | Serious/critical | All violations | URL |",
            "|---|---|---|---|---|",
        ]
        for scan in sorted(scans, key=lambda s: (str(s.get("project")), str(s.get("label")))):
            out.append(
                f"| {scan.get('project')} | {scan.get('label')} | "
                f"{scan.get('seriousOrCriticalCount')} | {len(scan.get('violations', []))} | "
                f"`{scan.get('url')}` |"
            )
        out += ["", "### Rules hit (count of scans)", ""]
        if rule_counts:
            out += ["| Rule [impact] | Scans |", "|---|---|"]
            out += [f"| `{rule}` | {n} |" for rule, n in rule_counts.most_common()]
        else:
            out.append("No violations reported by axe on the scanned pages.")
        out.append("")
    out += ["## Manual checklist status", ""]
    if not rows:
        out += ["Checklist not found; treat all manual checks as not done.", ""]
    else:
        out += ["| Status | Rows |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in sorted(status_counts.items())]
        unknown = {r["status"] for r in rows if r["status"].strip().lower() not in KNOWN_STATUS}
        if unknown:
            out += ["", f"Unrecognised status values (treated as not passed): {sorted(unknown)}"]
        out += [
            "",
            "`Eng only` means automated coverage exists; it is **not** a manual pass. "
            "Source: `docs/evidence/a11y-manual-checklist.md`.",
            "",
        ]
    out += [
        "## Not covered",
        "",
        "- Screen-reader and keyboard-only manual passes unless recorded in the checklist.",
        "- Firefox/WebKit (only with `PLAYWRIGHT_CROSS_BROWSER=1`), real mobile devices.",
        "- WCAG 2.2-specific criteria beyond what axe covers, and non-covered routes "
        "(scribe, records, grids, admin).",
        "",
        "To make a sign-off claim possible: complete the checklist (Pass/N/A with evidence) "
        "and add `docs/evidence/wcag-signoff.json` with "
        f"`{', '.join(SIGNOFF_FIELDS)}`.",
        "",
    ]
    return "\n".join(line for line in out if line is not None) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--scans", type=Path, default=DEFAULT_SCANS)
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    parser.add_argument("--signoff", type=Path, default=DEFAULT_SIGNOFF)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="exit 1 when no scans were found")
    args = parser.parse_args()

    scans = load_scans(args.scans)
    if args.check and not scans:
        print(f"error: no axe scan records in {args.scans}", file=sys.stderr)
        return 1
    rows = parse_checklist(args.checklist)
    signoff, problems = load_signoff(args.signoff)
    report = render(scans, rows, signoff, problems, args.scans)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"wrote {args.out} (scans={len(scans)}, checklist_rows={len(rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
