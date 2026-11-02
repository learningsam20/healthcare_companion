"""Word/character error rate helpers for actual STT/OCR run artefacts (G-05).

Does not invent hypotheses. Pass --run PATH to a JSON produced by a live Whisper/OCR
job: { "cases": [ {"id", "reference", "hypothesis", "modality"? } ] }.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _normalize(text: str) -> str:
    """Lowercase and strip punctuation for ASR scoring (words/letters only)."""
    lowered = text.lower()
    stripped = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return " ".join(stripped.split())


def wer(reference: str, hypothesis: str) -> float:
    ref = _normalize(reference).split()
    hyp = _normalize(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    rows = len(ref) + 1
    cols = len(hyp) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dp[i][0] = i
    for j in range(cols):
        dp[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[-1][-1] / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    ref = list(_normalize(reference).replace(" ", ""))
    hyp = list(_normalize(hypothesis).replace(" ", ""))
    if not ref:
        return 0.0 if not hyp else 1.0
    rows = len(ref) + 1
    cols = len(hyp) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        dp[i][0] = i
    for j in range(cols):
        dp[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[-1][-1] / len(ref)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="Actual STT/OCR run JSON (reference+hypothesis from live output)",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.run.exists():
        print(json.dumps({"status": "missing_run", "path": str(args.run)}))
        return 2
    fixture = json.loads(args.run.read_text(encoding="utf-8"))
    if fixture.get("synthetic") is True:
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "synthetic authored runs are not accepted as G-05 evidence",
                }
            )
        )
        return 2
    rows = []
    for case in fixture.get("cases") or []:
        ref = case["reference"]
        hyp = case["hypothesis"]
        if case.get("modality") == "ocr":
            score = cer(ref, hyp)
            metric = "cer"
        else:
            score = wer(ref, hyp)
            metric = "wer"
        rows.append(
            {
                "id": case.get("id"),
                "metric": metric,
                "score": round(score, 4),
                "language": case.get("language"),
            }
        )
    report = {
        "source_run": str(args.run),
        "status": "measured",
        "cases": rows,
        "mean": round(sum(r["score"] for r in rows) / len(rows), 4) if rows else None,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
