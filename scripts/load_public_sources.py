#!/usr/bin/env python3
"""FR-DATA-01 public-source download + inventory (actual files only).

Never invents row counts. Seed/sample is out of scope here (use load-data.sh --sample).
Requires Kaggle credentials in the operator environment for --download.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict[str, Any]:
    path = ROOT / "config" / "data_sources.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def public_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (cfg.get("sources") or []) if s.get("kind") == "public" and s.get("enabled")]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        next(reader, None)
        return sum(1 for _ in reader)


def largest_csv(directory: Path) -> Path | None:
    csvs = sorted(directory.rglob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)
    return csvs[0] if csvs else None


def kaggle_configured() -> bool:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return True
    return (Path.home() / ".kaggle" / "kaggle.json").exists()


def download_dataset(slug: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "datasets", "download", "-d", slug, "-p", str(dest), "--force"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "kaggle CLI not found. Install `kaggle` and set KAGGLE_USERNAME/KAGGLE_KEY "
            "(or ~/.kaggle/kaggle.json). Do not invent rows."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"kaggle download failed for {slug}: {exc.stderr or exc.stdout}") from exc
    for zpath in dest.glob("*.zip"):
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(dest)


def inventory_source(src: dict[str, Any], raw_root: Path) -> dict[str, Any]:
    sid = str(src["id"])
    dest = raw_root / sid
    row: dict[str, Any] = {
        "id": sid,
        "name": src.get("name"),
        "kaggle": src.get("kaggle"),
        "licence": src.get("licence"),
        "pack_rows_context": src.get("pack_rows_context"),
        "path": str(dest.relative_to(ROOT)) if dest.exists() else None,
        "present": dest.exists() and any(dest.iterdir()) if dest.exists() else False,
        "sha256": None,
        "row_count": None,
        "csv": None,
        "status": "missing",
    }
    if not row["present"]:
        return row
    csv_path = largest_csv(dest)
    if csv_path is None:
        # Hash zip or any single file if no CSV
        files = [p for p in dest.rglob("*") if p.is_file() and p.suffix != ".zip"]
        if not files:
            files = [p for p in dest.glob("*.zip") if p.is_file()]
        if files:
            target = max(files, key=lambda p: p.stat().st_size)
            row["sha256"] = sha256_file(target)
            row["status"] = "present_no_csv"
        return row
    row["csv"] = str(csv_path.relative_to(ROOT))
    row["sha256"] = sha256_file(csv_path)
    row["row_count"] = count_csv_rows(csv_path)
    expected = src.get("expected_sha256")
    if expected and expected != row["sha256"]:
        row["status"] = "hash_mismatch"
    else:
        row["status"] = "inventoried"
    return row


def update_contract(sid: str, inv: dict[str, Any], checked_at: str) -> None:
    path = ROOT / "docs" / "data-contracts" / f"{sid}.md"
    if not path.exists() or inv.get("row_count") is None:
        return
    text = path.read_text(encoding="utf-8")
    replacements = {
        "| Exact row count | *Pending actual inventory* |": f"| Exact row count | {inv['row_count']} |",
        "| SHA-256 | *Pending actual inventory* |": f"| SHA-256 | `{inv['sha256']}` |",
        "| Checked at | *Pending* |": f"| Checked at | {checked_at} |",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download via Kaggle CLI")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source id (repeatable) or 'all'",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Evidence JSON path (default docs/evidence/public-source-inventory-<stamp>.json)",
    )
    args = parser.parse_args()
    cfg = load_config()
    raw_root = ROOT / str(cfg.get("raw_dir") or "data/raw")
    sources = public_sources(cfg)
    wanted = set(args.source)
    if not wanted or "all" in wanted:
        selected = sources
    else:
        selected = [s for s in sources if s["id"] in wanted]
        unknown = wanted - {s["id"] for s in selected} - {"all"}
        if unknown:
            print(f"unknown source id(s): {sorted(unknown)}", file=sys.stderr)
            return 2
    if args.download:
        if not kaggle_configured():
            print(
                "Kaggle credentials missing. Set KAGGLE_USERNAME and KAGGLE_KEY "
                "(or ~/.kaggle/kaggle.json). Refusing to invent public-source rows. "
                "Use scripts/load-data.sh --sample for the seed profile only.",
                file=sys.stderr,
            )
            return 2
        for src in selected:
            slug = src.get("kaggle")
            if not slug:
                continue
            print(f"downloading {src['id']} ({slug})…", flush=True)
            download_dataset(str(slug), raw_root / str(src["id"]))
    checked_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    inventory = [inventory_source(src, raw_root) for src in selected]
    for inv in inventory:
        update_contract(str(inv["id"]), inv, checked_at)
    missing = [i["id"] for i in inventory if i["status"] in {"missing", "hash_mismatch"}]
    report = {
        "generated_at": checked_at,
        "rule": "Actual public files only; seed/sample is separate (FR-DATA-12).",
        "sources": inventory,
        "missing": missing,
        "status": "passed" if not missing else "incomplete",
        "g2": "G2 requires all five public sources inventoried with exact counts and licences.",
    }
    if args.out is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        out = ROOT / "docs" / "evidence" / f"public-source-inventory-{stamp}.json"
    else:
        out = args.out
    out = out if out.is_absolute() else ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    try:
        rel = out.relative_to(ROOT)
    except ValueError:
        rel = out
    print(f"wrote {rel}", file=sys.stderr)
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
