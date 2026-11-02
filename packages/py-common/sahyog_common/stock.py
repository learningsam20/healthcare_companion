"""Pharmacy stock adapter over a configured CSV extract.

The extract is the source of truth for the stock tool. No substitution is ever
suggested: callers receive quantity, clinic, source and an explicit stale flag.
"""

from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOW_STOCK_THRESHOLD = 20


class StockUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StockItem:
    sku: str
    drug_name: str
    form: str
    strength: str
    quantity: int
    clinic_code: str
    updated_at: dt.datetime
    source: str

    def as_dict(self, *, now: dt.datetime, stale_after_minutes: int) -> dict[str, Any]:
        age_minutes = max(0, int((now - self.updated_at).total_seconds() // 60))
        stale = age_minutes > stale_after_minutes
        if stale:
            status = "unknown"
        elif self.quantity <= 0:
            status = "not_available"
        elif self.quantity <= LOW_STOCK_THRESHOLD:
            status = "low"
        else:
            status = "in_stock"
        return {
            "sku": self.sku,
            "drug_name": self.drug_name,
            "form": self.form,
            "strength": self.strength,
            "quantity": self.quantity,
            "clinic_code": self.clinic_code,
            "source": self.source,
            "as_of": self.updated_at.isoformat(),
            "age_minutes": age_minutes,
            "stale": stale,
            "status": status,
        }


def _parse_timestamp(value: str) -> dt.datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def load_csv(path: str | Path, *, source_label: str | None = None) -> list[StockItem]:
    source_path = Path(path)
    if not source_path.exists():
        raise StockUnavailable("stock source is not configured")
    items: list[StockItem] = []
    try:
        with source_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                items.append(
                    StockItem(
                        sku=str(row["sku"]).strip(),
                        drug_name=str(row["drug_name"]).strip(),
                        form=str(row.get("form", "")).strip(),
                        strength=str(row.get("strength", "")).strip(),
                        quantity=int(row.get("quantity", 0)),
                        clinic_code=str(row["clinic_code"]).strip(),
                        updated_at=_parse_timestamp(str(row["updated_at"])),
                        source=source_label or str(row.get("source", "csv")).strip(),
                    )
                )
    except (KeyError, TypeError, ValueError) as exc:
        raise StockUnavailable("stock source is malformed") from exc
    return items


def find(items: list[StockItem], *, drug_name: str, clinic_code: str) -> StockItem | None:
    normalized = drug_name.strip().casefold()
    candidates = [
        item
        for item in items
        if item.clinic_code == clinic_code and item.drug_name.casefold() == normalized
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.updated_at)


def search(
    items: list[StockItem], *, query: str | None, clinic_code: str | None
) -> list[StockItem]:
    needle = (query or "").strip().casefold()
    rows = [
        item
        for item in items
        if (clinic_code is None or item.clinic_code == clinic_code)
        and (not needle or needle in item.drug_name.casefold() or needle in item.sku.casefold())
    ]
    return sorted(rows, key=lambda item: (item.drug_name, item.clinic_code))
