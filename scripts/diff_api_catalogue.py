#!/usr/bin/env python3
"""Diff the as-built OpenAPI catalogue against the architecture §7.5 design tables (G-38).

Inputs (no live API needed):
  docs/evidence/openapi-catalogue.json   (from scripts/regen_architecture_catalogue.py)
  docs/architecture.md                   (§7.5 tables)

Outputs:
  docs/evidence/api-catalogue-diff.json
  docs/evidence/api-catalogue-diff.md

``design_only`` rows are the leftovers: design-listed method+path pairs with no as-built
equivalent. This script reports them; it never marks anything out of scope. Out-of-scope
needs a product sign-off recorded in docs/evidence/api-leftovers-product-note.md.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\|\s*(GET|POST|PUT|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|")
PARAM = re.compile(r"\{[^}/]+\}")

# Design (method, path) -> (as-built method, as-built path, note). Targets are verified
# against the catalogue at run time; a missing target is reported, never assumed.
_S = "/api/v1/scribe"
_R = "/api/v1/records/documents"
_P = "/api/v1/pharmacy/stock"
RENAMES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("GET", "/api/v1/me"): ("GET", "/api/v1/auth/me", "identity under /auth"),
    ("GET", "/api/v1/me/notifications"): ("GET", "/api/v1/notifications", "own by default"),
    ("POST", "/api/v1/me/notifications/{id}/read"): (
        "POST",
        "/api/v1/notifications/{notification_id}/read",
        "owner-only",
    ),
    ("GET", "/api/v1/me/notifications/{id}/deliveries"): (
        "GET",
        "/api/v1/notifications/{notification_id}",
        "deliveries embedded in detail",
    ),
    ("POST", "/api/v1/me/export"): ("GET", "/api/v1/me/export", "GET, not POST"),
    ("GET", "/api/v1/slots"): ("GET", "/api/v1/doctors/{doctor_name}/slots", "per doctor"),
    ("GET", "/api/v1/documents"): ("GET", _R, "records prefix"),
    ("GET", "/api/v1/documents/{id}"): ("GET", _R + "/{document_id}", "records prefix"),
    ("DELETE", "/api/v1/documents/{id}"): ("DELETE", _R + "/{document_id}", "records prefix"),
    ("GET", "/api/v1/documents/{id}/download-url"): (
        "GET",
        _R + "/{document_id}/download",
        "streamed download, not a presigned URL",
    ),
    ("POST", "/api/v1/documents/uploads"): (
        "POST",
        _R,
        "single multipart upload; two-step presign not built",
    ),
    ("POST", "/api/v1/documents/{id}/complete"): (
        "POST",
        _R + "/{document_id}/ingest",
        "ingest trigger replaces upload-complete",
    ),
    ("GET", "/api/v1/documents/{id}/status"): (
        "GET",
        _R + "/{document_id}",
        "status is a field of document detail",
    ),
    ("GET", "/api/v1/citations/{chunk_id}"): (
        "GET",
        "/api/v1/chat/citations/{chunk_id}",
        "chat prefix",
    ),
    ("POST", "/api/v1/encounters"): ("POST", _S + "/encounters", "scribe prefix"),
    ("GET", "/api/v1/encounters/{id}"): ("GET", _S + "/encounters/{encounter_id}", "scribe prefix"),
    ("POST", "/api/v1/encounters/{id}/audio/uploads"): (
        "POST",
        _S + "/encounters/{encounter_id}/audio",
        "multipart audio upload",
    ),
    ("POST", "/api/v1/encounters/{id}/audio/{audio_id}/complete"): (
        "POST",
        _S + "/encounters/{encounter_id}/audio/{transcript_id}/complete",
        "transcript id",
    ),
    ("POST", "/api/v1/encounters/{id}/scribe-runs"): (
        "POST",
        _S + "/encounters/{encounter_id}/runs",
        "shorter name",
    ),
    ("GET", "/api/v1/notes"): ("GET", _S + "/notes", "scribe prefix"),
    ("GET", "/api/v1/notes/{id}"): ("GET", _S + "/notes/{note_id}", "scribe prefix"),
    ("GET", "/api/v1/notes/{id}/versions"): (
        "GET",
        _S + "/notes/{note_id}/versions",
        "scribe prefix",
    ),
    ("GET", "/api/v1/notes/{id}/sources"): (
        "GET",
        _S + "/notes/{note_id}/sources",
        "scribe prefix",
    ),
    ("GET", "/api/v1/notes/{id}/download"): (
        "GET",
        _S + "/notes/{note_id}/download",
        "scribe prefix",
    ),
    ("POST", "/api/v1/notes/{id}/reservations"): (
        "POST",
        _S + "/notes/{note_id}/reservations",
        "scribe prefix",
    ),
    ("GET", "/api/v1/stock"): ("GET", _P, "pharmacy prefix"),
    ("GET", "/api/v1/stock/{medicine_id}"): ("GET", _P + "/{item_id}", "item id, not medicine id"),
    ("GET", "/api/v1/consents/{id}"): ("GET", "/api/v1/consents", "list only; no get-by-id"),
    ("DELETE", "/api/v1/consents/{id}"): (
        "POST",
        "/api/v1/consents/{consent_id}/revoke",
        "revoke action, not DELETE",
    ),
    ("GET", "/api/v1/audit/events"): ("GET", "/api/v1/admin/audit", "admin prefix"),
    ("GET", "/api/v1/audit/events/export"): ("GET", "/api/v1/admin/audit/export", "admin prefix"),
    ("PATCH", "/api/v1/review-queue/{id}"): (
        "POST",
        "/api/v1/review-queue/{task_id}/claim",
        "claim action",
    ),
    ("POST", "/api/v1/review-queue/{id}/resolve"): (
        "POST",
        "/api/v1/review-queue/{task_id}/close",
        "close action",
    ),
    ("GET", "/api/v1/admin/feature-flags"): ("GET", "/api/v1/admin/flags", "shorter name"),
    ("PATCH", "/api/v1/admin/feature-flags/{key}"): (
        "PATCH",
        "/api/v1/admin/flags/{key}",
        "shorter name",
    ),
    ("GET", "/api/v1/analytics/evals"): ("GET", "/api/v1/analytics/evaluations", "full word"),
    ("GET", "/api/v1/analytics/eval-runs"): (
        "GET",
        "/api/v1/analytics/evaluations",
        "run list is part of evaluations",
    ),
    ("GET", "/api/v1/analytics/finops/usage"): (
        "GET",
        "/api/v1/analytics/finops",
        "usage in summary",
    ),
    ("PATCH", "/api/v1/analytics/finops/budgets/{id}"): (
        "PUT",
        "/api/v1/analytics/finops/budgets",
        "bulk PUT",
    ),
    ("PATCH", "/api/v1/analytics/finops/savings/{id}"): (
        "POST",
        "/api/v1/analytics/finops/savings",
        "savings recorded via POST",
    ),
    ("POST", "/api/v1/analytics/finops/export"): ("GET", "/api/v1/analytics/finops/export", "GET"),
    ("GET", "/api/v1/analytics/metrics/{key}"): (
        "GET",
        "/api/v1/analytics/metrics",
        "full catalogue, filter client-side",
    ),
    ("POST", "/api/v1/analytics/insights/{id}/action"): (
        "POST",
        "/api/v1/analytics/insights/{insight_id}/decision",
        "decision verb",
    ),
    ("GET", "/api/v1/admin/config"): ("GET", "/api/v1/admin/governance", "governance settings"),
    ("PATCH", "/api/v1/admin/config/{key}"): (
        "PATCH",
        "/api/v1/admin/governance",
        "governance settings (body keys)",
    ),
}

# Proposed out of scope. NOT a decision: needs product sign-off (see the product note).
PROPOSED_OUT_OF_SCOPE: dict[tuple[str, str], str] = {
    ("GET", "/metrics"): "Telemetry is OTLP push to the collector; no API pull endpoint.",
    (
        "GET",
        "/api/v1/admin/users",
    ): "Keycloak user admin is an operator script (keycloak_admin.py).",
    ("POST", "/api/v1/admin/users/invite"): "Operator script: scripts/add-user.sh.",
    ("PATCH", "/api/v1/admin/users/{id}/roles"): "Operator script: scripts/add-user.sh --confirm.",
    ("GET", "/api/v1/admin/health"): "Covered by /healthz, /readyz and scripts/status.sh.",
    ("GET", "/api/v1/admin/data-catalogue"): "Catalogue lives in docs/data-contracts.",
    ("POST", "/api/v1/analytics/refresh"): "Snapshot is an ARQ cron job; no manual HTTP trigger.",
}

# Real functionality not built; needs a product decision (implement or descope).
DEFERRED: dict[tuple[str, str], str] = {
    ("PATCH", "/api/v1/me/preferences"): "Preferences are the memory API (PUT /me/memory).",
    ("PATCH", "/api/v1/me/memory/settings"): "Opt-out is the opt_out key + POST /me/memory/purge.",
    ("GET", "/api/v1/scribe/runs/{id}/sources"): "Sources are on notes, not on runs.",
    ("GET", "/api/v1/scribe/runs/{id}/events"): "Scribe SSE progress stream not built.",
    ("POST", "/api/v1/scribe/runs/{id}/resume"): "Scribe run resume endpoint not built.",
}


def normalise(path: str) -> str:
    return PARAM.sub("{}", path.split("?")[0].rstrip("/") or "/")


def parse_design(text: str) -> list[tuple[str, str]]:
    start = text.index("### 7.5 Endpoint catalogue")
    end = text.index("### 7.6 SSE protocol")
    rows: list[tuple[str, str]] = []
    for line in text[start:end].splitlines():
        match = ROW.match(line)
        if match:
            rows.append((match.group(1), match.group(2)))
    return rows


def load_as_built(path: Path) -> dict[tuple[str, str], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (method, normalise(route)): route
        for route, methods in data["paths"].items()
        for method in methods
    }


def diff(design: list[tuple[str, str]], built: dict[tuple[str, str], str]) -> dict[str, list]:
    seen: set[tuple[str, str]] = set()
    matched: list[dict[str, str]] = []
    renamed: list[dict[str, str]] = []
    proposed: list[dict[str, str]] = []
    deferred: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    bad_targets: list[dict[str, str]] = []
    claimed: set[tuple[str, str]] = set()
    for method, route in design:
        key = (method, normalise(route))
        if key in seen:
            continue
        seen.add(key)
        entry = {"method": method, "path": route}
        raw = (method, route)
        if key in built:
            matched.append(entry)
            claimed.add(key)
        elif raw in RENAMES:
            target_method, target_path, note = RENAMES[raw]
            target = (target_method, normalise(target_path))
            row = {**entry, "as_built": f"{target_method} {target_path}", "note": note}
            if target in built:
                renamed.append(row)
                claimed.add(target)
            else:
                bad_targets.append(row)
        elif raw in PROPOSED_OUT_OF_SCOPE:
            proposed.append({**entry, "reason": PROPOSED_OUT_OF_SCOPE[raw]})
        elif raw in DEFERRED:
            deferred.append({**entry, "reason": DEFERRED[raw]})
        else:
            unresolved.append(entry)
    as_built_only = [
        {"method": m, "path": p} for (m, n), p in sorted(built.items()) if (m, n) not in claimed
    ]
    return {
        "matched": matched,
        "renamed": renamed,
        "proposed_out_of_scope": proposed,
        "deferred_not_built": deferred,
        "unresolved": unresolved,
        "invalid_rename_targets": bad_targets,
        "as_built_only": as_built_only,
    }


def to_markdown(result: dict[str, list], stamp: str) -> str:
    lines = [
        "# API catalogue diff (design §7.5 vs as-built OpenAPI)",
        "",
        f"Generated: `{stamp}` by `scripts/diff_api_catalogue.py`",
        "",
        "| Bucket | Count | Meaning |",
        "| --- | ---: | --- |",
        f"| Matched | {len(result['matched'])} | Same method + path in design and as-built |",
        f"| Renamed | {len(result['renamed'])} | Capability exists under a different path/verb |",
        f"| Proposed out of scope | {len(result['proposed_out_of_scope'])} | "
        "Script-only / replaced / infra; **awaiting product sign-off** |",
        f"| Deferred (not built) | {len(result['deferred_not_built'])} | "
        "Functionality absent; product must implement or descope |",
        f"| Unresolved | {len(result['unresolved'])} | Not yet classified |",
        f"| Invalid rename targets | {len(result['invalid_rename_targets'])} | "
        "Mapping points at a path that is not as-built |",
        f"| As-built only | {len(result['as_built_only'])} | Not in design tables |",
        "",
        "Nothing here is marked out of scope by engineering. Status of the product decision:",
        "[api-leftovers-product-note.md](./api-leftovers-product-note.md).",
    ]

    def table(title: str, rows: list[dict[str, str]], cols: tuple[str, ...]) -> None:
        if not rows:
            return
        lines.extend(["", f"## {title}", "", "| " + " | ".join(cols) + " |"])
        lines.append("| " + " | ".join("---" for _ in cols) + " |")
        for row in rows:
            cells = [f"`{row['method']} {row['path']}`"]
            cells += [str(row.get(col, "")) for col in cols[1:]]
            lines.append("| " + " | ".join(cells) + " |")

    table("Renamed (design to as-built)", result["renamed"], ("Design", "as_built", "note"))
    table(
        "Proposed out of scope (unsigned)",
        result["proposed_out_of_scope"],
        ("Design", "reason"),
    )
    table("Deferred - not built", result["deferred_not_built"], ("Design", "reason"))
    table("Unresolved", result["unresolved"], ("Design",))
    table("Invalid rename targets", result["invalid_rename_targets"], ("Design", "as_built"))
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalogue", type=Path, default=ROOT / "docs/evidence/openapi-catalogue.json"
    )
    parser.add_argument("--architecture", type=Path, default=ROOT / "docs/architecture.md")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "docs/evidence")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when any design row is unresolved or a rename target is invalid",
    )
    args = parser.parse_args()

    design = parse_design(args.architecture.read_text(encoding="utf-8"))
    result = diff(design, load_as_built(args.catalogue))
    stamp = datetime.now(UTC).isoformat()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": stamp,
        "design_rows": len(design),
        "counts": {key: len(value) for key, value in result.items()},
        **result,
    }
    (args.out_dir / "api-catalogue-diff.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.out_dir / "api-catalogue-diff.md").write_text(
        to_markdown(result, stamp), encoding="utf-8"
    )
    print(json.dumps({"design_rows": len(design), **payload["counts"]}, indent=2))
    if args.strict and (result["unresolved"] or result["invalid_rename_targets"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
