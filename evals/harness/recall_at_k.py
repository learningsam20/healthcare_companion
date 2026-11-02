"""Measure retrieval recall@k on mixed-script fixtures (G-03).

Offline: scores precomputed ``retrieved_chunk_ids`` against ``relevant_chunk_ids``.
Live (``--live``): calls ``POST /api/v1/records/search`` and scores term hits in
returned chunk text against ``relevant_terms`` (fixture IDs are synthetic and are
not compared to live UUIDs).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
DEFAULT_FIXTURE = ROOT / "evals" / "fixtures" / "mixed_script_recall.json"
DEFAULT_PATIENT_ID = "20000000-0000-4000-8000-000000000001"


def recall_at_k(relevant: list[str], retrieved: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    hit = sum(1 for item in retrieved[:k] if item in set(relevant))
    return hit / len(relevant)


def term_recall(relevant_terms: list[str], texts: list[str], k: int) -> float:
    if not relevant_terms:
        return 0.0
    joined = " ".join(texts[:k]).lower()
    hit = sum(1 for term in relevant_terms if term.lower() in joined)
    return hit / len(relevant_terms)


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def live_search(
    *,
    patient_id: str,
    query: str,
    k: int,
    username: str,
) -> list[dict[str, Any]]:
    from ops_client import OpsClient  # noqa: WPS433

    client = OpsClient()
    payload = client.post(
        "/api/v1/records/search",
        {"patient_id": patient_id, "query": query, "top_k": k},
        username=username,
    )
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(
            payload.get("results") or payload.get("hits") or payload.get("items") or []
        )
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", type=Path, help="Write JSON report")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call live records search (requires stack + OpsClient credentials)",
    )
    parser.add_argument("--patient-id", default=DEFAULT_PATIENT_ID)
    parser.add_argument("--username", default="doctor.rao")
    args = parser.parse_args(argv)

    live = args.live or os.environ.get("SAHYOG_RECALL_LIVE") == "1"

    if not args.fixture.exists():
        print(f"error: missing fixture {args.fixture}", file=sys.stderr)
        return 2
    fixture = load_fixture(args.fixture)
    cases = fixture.get("cases") or []
    rows = []
    live_errors: list[str] = []
    for case in cases:
        relevant = list(case.get("relevant_chunk_ids") or [])
        terms = list(case.get("relevant_terms") or [])
        retrieved_ids = list(case.get("retrieved_chunk_ids") or [])
        texts: list[str] = []
        mode = "fixture_ids"
        score: float | None
        if live:
            mode = "live_terms"
            try:
                hits = live_search(
                    patient_id=args.patient_id,
                    query=str(case.get("query") or ""),
                    k=args.k,
                    username=args.username,
                )
                retrieved_ids = [str(h.get("chunk_id") or h.get("id") or "") for h in hits]
                texts = [
                    str(h.get("snippet") or h.get("text") or h.get("content") or "") for h in hits
                ]
                score = term_recall(terms, texts, args.k) if terms else None
            except Exception as exc:  # noqa: BLE001 — record and continue
                live_errors.append(f"{case.get('id')}: {exc}")
                retrieved_ids = []
                score = None
        else:
            score = recall_at_k(relevant, retrieved_ids, args.k)
        rows.append(
            {
                "id": case.get("id"),
                "language": case.get("language"),
                "mode": mode,
                "recall_at_k": None if score is None else round(score, 4),
                "k": args.k,
                "relevant": len(terms) if live else len(relevant),
                "retrieved": len([x for x in retrieved_ids[: args.k] if x]),
                "retrieved_chunk_ids": retrieved_ids[: args.k],
            }
        )
    scored = [r["recall_at_k"] for r in rows if r["recall_at_k"] is not None]
    mean = sum(scored) / len(scored) if scored else None
    report: dict[str, Any] = {
        "dataset": fixture.get("dataset"),
        "k": args.k,
        "mean_recall_at_k": None if mean is None else round(mean, 4),
        "cases": rows,
        "live": {
            "requested": live,
            "executed": live and not live_errors,
            "partial": bool(live and live_errors and scored),
            "errors": live_errors,
            "patient_id": args.patient_id if live else None,
            "scoring": "relevant_terms in retrieved text" if live else "fixture chunk ids",
        },
        "limitations": [
            "Offline scores use fixture retrieved_chunk_ids (synthetic IDs).",
            "Live mode scores term overlap in retrieved chunk text, not fixture IDs.",
            "Not a production retrieval SLA claim.",
        ],
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    if live and live_errors and not scored:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
