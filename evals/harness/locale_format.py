"""G-20 locale formatting checks against authored fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def format_currency_inr(value: float, locale: str) -> str:
    # Stable demo formatter (not full CLDR). Always include ₹ for IN locales.
    whole, frac = f"{value:,.2f}".split(".")
    return f"₹{whole}.{frac}"


def format_date_iso(iso: str, locale: str) -> str:
    y, m, d = iso.split("-")
    if locale.startswith("en"):
        return f"{d}/{m}/{y}"
    return f"{y}-{m}-{d}"


def format_number(value: float, locale: str) -> str:
    return f"{value:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("evals/fixtures/locale_format.json"),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    rows = []
    failures = []
    for case in fixture["cases"]:
        kind = case["kind"]
        locale = case["locale"]
        if kind == "currency":
            rendered = format_currency_inr(float(case["value"]), locale)
        elif kind == "date":
            rendered = format_date_iso(case["iso"], locale)
        else:
            rendered = format_number(float(case["value"]), locale)
        ok = all(tok in rendered for tok in case.get("expect_contains") or [])
        rows.append({"id": case["id"], "rendered": rendered, "ok": ok})
        if not ok:
            failures.append(case["id"])
    report = {
        "dataset": fixture["dataset"],
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "cases": rows,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
