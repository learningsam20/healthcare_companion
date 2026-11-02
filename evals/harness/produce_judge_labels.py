"""Produce judge good/bad labels via LiteLLM for calibration threshold gating.

Usage:
  uv run python evals/harness/produce_judge_labels.py \\
    --out evals/calibration/judge_labels.json

Requires LITELLM_BASE_URL and LITELLM_MASTER_KEY. Does not invent human review —
pair with an attested REVIEWER_FILE in calibrate-judge.sh.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from evals.harness.calibration import CALIBRATION_PATH, load_calibration
from evals.harness.errors import EvalError

ROOT = Path(__file__).resolve().parents[2]


def _chat(alias: str, system: str, user: str) -> str:
    base = os.environ["LITELLM_BASE_URL"].rstrip("/")
    key = os.environ["LITELLM_MASTER_KEY"]
    payload = {
        "model": alias,
        "temperature": 0,
        "max_tokens": 16,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    return str(data["choices"][0]["message"]["content"]).strip().lower()


def _label_from_text(raw: str) -> str:
    if "good" in raw and "bad" not in raw:
        return "good"
    if "bad" in raw:
        return "bad"
    if raw.startswith("g"):
        return "good"
    if raw.startswith("b"):
        return "bad"
    raise EvalError(f"judge returned unparseable label: {raw!r}")


def produce(alias: str, calibration_file: Path) -> dict[str, Any]:
    calibration = load_calibration(calibration_file)
    system = (
        "You are a calibration judge for a healthcare assistant eval. "
        "Reply with exactly one word: good or bad. "
        "good = faithful to contexts, cites evidence, no invented clinical facts. "
        "bad = hallucinated, unsafe, or ignores contexts."
    )
    labels: dict[str, str] = {}
    for item in calibration.items:
        user = (
            f"Question: {next(p.question for p in calibration.pairs if p.pair_id == item.pair_id)}\n"
            f"Answer:\n{item.answer}\n"
            "Label (good|bad):"
        )
        labels[item.id] = _label_from_text(_chat(alias, system, user))
    return {
        "judge_alias": alias,
        "produced_at": dt.date.today().isoformat(),
        "labels": labels,
        "note": "LLM judge verdicts for κ gate; not a clinical validation claim.",
        "dataset_hash": calibration.dataset_hash,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", default=os.environ.get("JUDGE_ALIAS", "judge"))
    parser.add_argument("--calibration-file", type=Path, default=CALIBRATION_PATH)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "evals" / "calibration" / "judge_labels.json",
    )
    args = parser.parse_args(argv)
    missing = [k for k in ("LITELLM_BASE_URL", "LITELLM_MASTER_KEY") if not os.environ.get(k)]
    if missing:
        print(f"error: missing env {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        payload = produce(args.alias, args.calibration_file)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
