#!/usr/bin/env python3
"""G-35: download the public datasets that need Kaggle credentials.

Fetches the sources marked ``kind: public`` in ``config/data_sources.yaml`` into
``data/raw/<source-id>/`` using the official ``kaggle`` CLI. Nothing is faked: if
credentials or the CLI are missing the script exits non-zero and writes no data,
and it never fabricates rows, counts or "downloaded" markers.

Credentials (any one):
  * env ``KAGGLE_USERNAME`` + ``KAGGLE_KEY``
  * env ``KAGGLE_API_TOKEN`` (new-style access token)
  * ``~/.kaggle/kaggle.json`` (``{"username": ..., "key": ...}``)
Some datasets also require accepting their terms once on kaggle.com while signed
in; a refusal from Kaggle is reported as a failure, not skipped.

Usage:
  scripts/download_public_sources.py --list                 # no creds needed
  scripts/download_public_sources.py --check-creds          # exit 0 only if usable
  scripts/download_public_sources.py --source appointments  # one source (repeatable)
  scripts/download_public_sources.py --source all           # all five (default)
  uv run python scripts/download_public_sources.py --source all
  scripts/download_public_sources.py --source all --force   # re-download existing

Exit codes:
  0  every selected source downloaded (or already present, unless --force)
  2  usage error / unknown source id
  3  Kaggle credentials missing
  4  ``kaggle`` CLI not installed
  5  one or more downloads failed (see stderr per source)

After a successful run, inventory (row counts, SHA-256, licence) with:
  uv run python scripts/load_public_sources.py --source all
Licences marked ``check_and_record`` must still be reviewed by a human before the
data is redistributed or used beyond internal evaluation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

EXIT_USAGE = 2
EXIT_NO_CREDS = 3
EXIT_NO_CLI = 4
EXIT_DOWNLOAD_FAILED = 5


def load_sources() -> tuple[Path, list[dict[str, Any]]]:
    cfg = yaml.safe_load((ROOT / "config" / "data_sources.yaml").read_text(encoding="utf-8")) or {}
    raw_root = ROOT / str(cfg.get("raw_dir") or "data/raw")
    sources = [
        s
        for s in (cfg.get("sources") or [])
        if s.get("kind") == "public" and s.get("enabled") and s.get("kaggle")
    ]
    return raw_root, sources


def credentials_present() -> str | None:
    """Return a label for the credential source found, or None when missing."""
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return "env:KAGGLE_USERNAME+KAGGLE_KEY"
    if os.environ.get("KAGGLE_API_TOKEN"):
        return "env:KAGGLE_API_TOKEN"
    config_dir = Path(os.environ.get("KAGGLE_CONFIG_DIR") or Path.home() / ".kaggle")
    cred_file = config_dir / "kaggle.json"
    if cred_file.is_file():
        try:
            payload = json.loads(cred_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if payload.get("username") and payload.get("key"):
            return f"file:{cred_file}"
    access_token = Path.home() / ".kaggle" / "access_token"
    if access_token.is_file() and access_token.read_text(encoding="utf-8").strip():
        return f"file:{access_token}"
    return None


def has_data(dest: Path) -> bool:
    return dest.is_dir() and any(p.is_file() and p.suffix != ".zip" for p in dest.rglob("*"))


def download_one(slug: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "datasets", "download", "-d", slug, "-p", str(dest), "--force"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(detail)
    zips = list(dest.glob("*.zip"))
    if not zips:
        raise RuntimeError("kaggle reported success but produced no archive")
    for archive in zips:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                # Zip-slip guard: only extract inside dest.
                target = (dest / member).resolve()
                if dest.resolve() not in target.parents and target != dest.resolve():
                    raise RuntimeError(f"unsafe path in archive: {member}")
            zf.extractall(dest)
    if not has_data(dest):
        raise RuntimeError("archive extracted but no data files found")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Kaggle-hosted public sources (credentials required).",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", action="append", default=[], help="source id or 'all'")
    parser.add_argument("--list", action="store_true", help="list downloadable sources and exit")
    parser.add_argument("--check-creds", action="store_true", help="verify credentials and exit")
    parser.add_argument("--force", action="store_true", help="re-download already-present data")
    args = parser.parse_args()

    raw_root, sources = load_sources()

    if args.list:
        for src in sources:
            print(f"{src['id']}\t{src['kaggle']}\t{src.get('licence')}\t-> {raw_root / src['id']}")
        return 0

    creds = credentials_present()
    if creds is None:
        print(
            "error: Kaggle credentials not found; nothing was downloaded.\n"
            "  Set KAGGLE_USERNAME and KAGGLE_KEY (or KAGGLE_API_TOKEN), or create\n"
            '  ~/.kaggle/kaggle.json with {"username": ..., "key": ...} (chmod 600).\n'
            "  Create a token at https://www.kaggle.com/settings. This script will not\n"
            "  invent public-source rows; use scripts/load-data.sh --sample for the\n"
            "  separate seed profile.",
            file=sys.stderr,
        )
        return EXIT_NO_CREDS
    if args.check_creds:
        print(f"ok: credentials found via {creds}")
        return 0

    if shutil.which("kaggle") is None:
        print(
            "error: `kaggle` CLI not found on PATH. Install it (e.g. `uv tool install kaggle` "
            "or `pip install kaggle`) and retry.",
            file=sys.stderr,
        )
        return EXIT_NO_CLI

    wanted = set(args.source) or {"all"}
    if "all" in wanted:
        selected = sources
    else:
        selected = [s for s in sources if s["id"] in wanted]
        unknown = wanted - {s["id"] for s in selected}
        if unknown:
            known = sorted(s["id"] for s in sources)
            print(f"error: unknown source id(s) {sorted(unknown)}; known: {known}", file=sys.stderr)
            return EXIT_USAGE

    failures: list[str] = []
    for src in selected:
        sid, slug = str(src["id"]), str(src["kaggle"])
        dest = raw_root / sid
        if has_data(dest) and not args.force:
            print(f"skip   {sid}: data already present in {dest} (use --force)")
            continue
        print(f"fetch  {sid}: kaggle:{slug} -> {dest}", flush=True)
        try:
            download_one(slug, dest)
        except Exception as exc:  # noqa: BLE001 - report per source, keep going
            print(f"FAILED {sid}: {exc}", file=sys.stderr)
            failures.append(sid)
        else:
            print(f"ok     {sid}")

    if failures:
        print(f"error: {len(failures)} download(s) failed: {failures}", file=sys.stderr)
        return EXIT_DOWNLOAD_FAILED
    print("done. Next: uv run python scripts/load_public_sources.py --source all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
