#!/usr/bin/env python3
"""G-01/G-02: inventory safety i18n keys and surface clinical sign-off in reports.

Writes:
  - docs/evidence/i18n-safety-key-audit.json
  - docs/evidence/clinical-i18n-report.md

Sign-off source of truth: docs/evidence/i18n-clinical-signoff.json
(copy from i18n-clinical-signoff.example.json when the clinical reviewer approves).
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("en", "hi", "mr")
# UI safety / clinical-facing keys (not only a literal "safety.*" prefix).
SAFETY_KEY_RE = re.compile(
    r"""["']((?:chat\.redFlag\w*|scribe\.redFlags|safety\.[a-z0-9_.]+))["']""",
    re.I,
)


def load_red_flag_ids(path: Path) -> set[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    flags = data.get("rules") or data.get("flags") or data.get("red_flags") or []
    ids: set[str] = set()
    for row in flags:
        if isinstance(row, dict) and row.get("id"):
            ids.add(str(row["id"]))
        elif isinstance(row, str):
            ids.add(row)
    return ids


def extract_keys(locale_dir: Path) -> set[str]:
    keys: set[str] = set()
    for path in locale_dir.rglob("*"):
        if path.suffix.lower() not in {".json", ".ts", ".tsx", ".js", ".po", ".yaml", ".yml"}:
            continue
        if "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        keys.update(m.group(1) for m in SAFETY_KEY_RE.finditer(text))
    return keys


def load_signoff(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def normalize_review(signoff: dict[str, Any] | None) -> dict[str, Any]:
    """Return a reportable review block; never invent an approval."""
    if not signoff:
        return {
            "review_status": "unreviewed",
            "approver_name": None,
            "approver_role": None,
            "signed_at": None,
            "visible_in_reports": True,
            "signoff_path": None,
            "note": "No i18n-clinical-signoff.json present.",
        }
    status = str(signoff.get("review_status") or "unreviewed").strip().lower()
    approver = signoff.get("approver") if isinstance(signoff.get("approver"), dict) else {}
    name = (approver or {}).get("name")
    role = (approver or {}).get("role")
    signed_at = signoff.get("signed_at")
    approved = (
        status in {"approved", "signed", "reviewed"}
        and bool(name)
        and bool(signed_at)
    )
    return {
        "review_status": "approved" if approved else "unreviewed",
        "approver_name": name if approved else None,
        "approver_role": role if approved else None,
        "signed_at": signed_at if approved else None,
        "locales": signoff.get("locales"),
        "catalogue": signoff.get("catalogue"),
        "scope_notes": signoff.get("scope_notes"),
        "attestation": signoff.get("attestation") if approved else None,
        "visible_in_reports": True,
        "signoff_path": "docs/evidence/i18n-clinical-signoff.json",
        "note": (
            None
            if approved
            else "Sign-off file present but incomplete (need review_status=approved, approver.name, signed_at)."
        ),
    }


def render_clinical_report(audit: dict[str, Any]) -> str:
    review = audit.get("clinical_review") or {}
    status = review.get("review_status", "unreviewed")
    lines = [
        "# Clinical i18n report (G-01 / G-02)",
        "",
        f"- Generated: `{audit.get('generated_at', '')}`",
        f"- Review status: **{status}**",
        f"- Gaps: G-01 (translation coverage), G-02 (clinical language validation)",
        "",
        "## Clinical reviewer sign-off",
        "",
    ]
    if status == "approved":
        lines.extend(
            [
                f"- Approver: **{review.get('approver_name')}**"
                + (f" ({review.get('approver_role')})" if review.get("approver_role") else ""),
                f"- Signed at: `{review.get('signed_at')}`",
                f"- Locales: {', '.join(review.get('locales') or [])}",
                f"- Catalogue: {review.get('catalogue') or '—'}",
                "",
                "### Attestation",
                "",
                str(review.get("attestation") or "—"),
                "",
            ]
        )
        if review.get("scope_notes"):
            lines.extend(["### Scope notes", "", str(review["scope_notes"]), ""])
    else:
        lines.extend(
            [
                "No approved clinical sign-off is on file.",
                "",
                f"- Detail: {review.get('note') or 'unreviewed'}",
                "- To record approval: copy `docs/evidence/i18n-clinical-signoff.example.json` → "
                "`docs/evidence/i18n-clinical-signoff.json`, fill approver/signed_at, set "
                "`review_status` to `approved`, then re-run `scripts/i18n_safety_key_audit.py`.",
                "",
                "Until then, hi/mr safety copy must **not** be claimed as clinically validated.",
                "",
            ]
        )

    lines.extend(
        [
            "## Safety key inventory",
            "",
            f"- Locales scanned: {', '.join(audit.get('locales_scanned') or [])}",
            f"- Safety keys found: **{len(audit.get('safety_keys_found') or [])}**",
            f"- Red-flag rule IDs in config: **{len(audit.get('red_flag_ids') or [])}**",
            "",
        ]
    )
    keys = audit.get("safety_keys_found") or []
    if keys:
        lines.append("| Key |")
        lines.append("|---|")
        for key in keys:
            lines.append(f"| `{key}` |")
        lines.append("")
    else:
        lines.extend(["No safety-pattern keys matched the inventory regex.", ""])

    lines.extend(
        [
            "## Honesty",
            "",
            "- This report surfaces sign-off status; it does not create approval.",
            "- Key inventory is not linguistic QA.",
            "- G-12 (medical-device validation) remains separate from G-01/G-02 copy review.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--red-flags",
        type=Path,
        default=ROOT / "config" / "red_flags.yaml",
    )
    parser.add_argument(
        "--locales-root",
        type=Path,
        default=ROOT / "apps" / "web" / "src",
    )
    parser.add_argument(
        "--signoff",
        type=Path,
        default=ROOT / "docs" / "evidence" / "i18n-clinical-signoff.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "evidence" / "i18n-safety-key-audit.json",
    )
    parser.add_argument(
        "--clinical-report",
        type=Path,
        default=ROOT / "docs" / "evidence" / "clinical-i18n-report.md",
    )
    args = parser.parse_args()

    flag_ids = load_red_flag_ids(args.red_flags) if args.red_flags.exists() else set()
    keys = extract_keys(args.locales_root)
    signoff = load_signoff(args.signoff)
    clinical_review = normalize_review(signoff)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    approved = clinical_review["review_status"] == "approved"
    report = {
        "status": "ready" if keys else "scaffolding",
        "generated_at": generated_at,
        "gaps": ["G-01", "G-02"],
        "locales_scanned": list(LOCALES),
        "red_flag_ids": sorted(flag_ids),
        "safety_keys_found": sorted(keys),
        "review_status": clinical_review["review_status"],
        "clinical_review": clinical_review,
        "missing_linguistic_qa": not approved,
        "note": (
            "Clinical sign-off recorded; inventory still not a substitute for ongoing locale QA."
            if approved
            else "Key inventory only; native-speaker / clinical review of hi/mr safety copy is still required."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.clinical_report.write_text(render_clinical_report(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"clinical report → {args.clinical_report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
