"""G-04: summarise existing eval evidence by language (no new LLM calls)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarise(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    slices: dict = {}
    for run in data.get("framework_runs") or []:
        if isinstance(run, dict) and isinstance(run.get("language_slices"), dict):
            slices[str(run.get("framework") or run.get("suite") or "run")] = run["language_slices"]
    if not slices and isinstance(data.get("by_language"), dict):
        slices["root"] = data["by_language"]
    return {
        "source": str(path),
        "language_slices": slices,
        "missing": not bool(slices),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inputs",
        nargs="*",
        type=Path,
        default=[
            Path("docs/evidence/eval-ragas-w3-20261025T083908Z.json"),
            Path("docs/evidence/eval-deepeval-x01-20261025T095159Z.json"),
        ],
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/evidence/language-eval-slice.json"),
    )
    args = parser.parse_args()
    report = {
        "status": "aggregated",
        "note": "Aggregates committed synthetic eval evidence; not a new model run.",
        "routing": "config/models.yaml language_routing",
        "slices": [summarise(p) if p.exists() else {"source": str(p), "missing": True} for p in args.inputs],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
