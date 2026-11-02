"""Edit-distance and review-time metrics between first draft and signed note."""

from __future__ import annotations

import datetime as dt
from typing import Any


def _normalize_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        # medicines list items
        parts = []
        for key in sorted(value.keys()):
            parts.append(f"{key}:{value[key]}")
        return "|".join(parts)
    return str(value)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    # Bound cost for very long clinical text.
    if len(a) > 4000 or len(b) > 4000:
        a, b = a[:4000], b[:4000]
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            ins = curr[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(ins, delete, sub))
        prev = curr
    return prev[-1]


def field_edit_distances(
    first_draft: dict[str, Any], signed: dict[str, Any]
) -> dict[str, Any]:
    fields = ("subjective", "objective", "assessment", "plan", "follow_up", "medicines")
    per_field: dict[str, int] = {}
    total = 0
    chars = 0
    for field in fields:
        left = _normalize_field(first_draft.get(field))
        right = _normalize_field(signed.get(field))
        if field == "medicines":
            left = _normalize_field(first_draft.get("medicines") or [])
            right = _normalize_field(signed.get("medicines") or [])
            if isinstance(first_draft.get("medicines"), list):
                left = "\n".join(
                    _normalize_field(item) for item in first_draft.get("medicines") or []
                )
            if isinstance(signed.get("medicines"), list):
                right = "\n".join(
                    _normalize_field(item) for item in signed.get("medicines") or []
                )
        dist = _levenshtein(left, right)
        per_field[field] = dist
        total += dist
        chars += max(len(left), len(right), 1)
    ratio = round(total / chars, 4) if chars else 0.0
    return {
        "per_field": per_field,
        "total": total,
        "normalized_ratio": ratio,
        "changed_fields": [f for f, d in per_field.items() if d > 0],
    }


def review_seconds(
    *,
    draft_ready_at: dt.datetime | None,
    signed_at: dt.datetime | None,
) -> float | None:
    if draft_ready_at is None or signed_at is None:
        return None
    left = draft_ready_at if draft_ready_at.tzinfo else draft_ready_at.replace(tzinfo=dt.UTC)
    right = signed_at if signed_at.tzinfo else signed_at.replace(tzinfo=dt.UTC)
    return max(0.0, round((right - left).total_seconds(), 1))
