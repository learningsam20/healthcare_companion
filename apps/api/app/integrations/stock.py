"""Pharmacy stock adapter. CSV or a configured HTTP API; never a fabricated quantity."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import httpx
from app.core.config import Settings
from sahyog_common.stock import StockItem, StockUnavailable, find, load_csv


class StockService:
    def __init__(self, settings: Settings, config: dict[str, Any]) -> None:
        self._settings = settings
        self._config = config
        self._root = settings.config_dir.parent

    @property
    def source_label(self) -> str:
        return str(self._config.get("source_label") or self._config.get("adapter", "csv"))

    @property
    def stale_after_minutes(self) -> int:
        return int(self._config.get("stale_after_minutes", 60))

    def _csv_path(self) -> Path:
        raw = str(self._config.get("csv_path", "config/stock.csv"))
        path = Path(raw)
        return path if path.is_absolute() else self._root / path

    async def _load(self) -> list[StockItem]:
        adapter = str(self._config.get("adapter", "csv"))
        if adapter == "csv":
            return load_csv(self._csv_path(), source_label=self.source_label)
        if adapter == "api":
            url = str(self._config.get("api_url", "")).strip()
            if not url:
                raise StockUnavailable("stock API is not configured")
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise StockUnavailable("stock API is unavailable") from exc
            return self._parse_api(payload)
        raise StockUnavailable("unsupported stock adapter")

    def _parse_api(self, payload: Any) -> list[StockItem]:
        rows = payload.get("items", []) if isinstance(payload, dict) else payload
        items: list[StockItem] = []
        try:
            for row in rows:
                items.append(
                    StockItem(
                        sku=str(row["sku"]),
                        drug_name=str(row["drug_name"]),
                        form=str(row.get("form", "")),
                        strength=str(row.get("strength", "")),
                        quantity=int(row.get("quantity", 0)),
                        clinic_code=str(row["clinic_code"]),
                        updated_at=dt.datetime.fromisoformat(
                            str(row["updated_at"]).replace("Z", "+00:00")
                        ),
                        source=self.source_label,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise StockUnavailable("stock API returned an invalid response") from exc
        return items

    async def lookup(self, *, drug_name: str, clinic_code: str) -> dict[str, Any]:
        now = dt.datetime.now(dt.UTC)
        try:
            item = find(await self._load(), drug_name=drug_name, clinic_code=clinic_code)
        except StockUnavailable as exc:
            return {
                "available": False,
                "status": "unknown",
                "reason": str(exc),
                "drug_name": drug_name,
                "clinic_code": clinic_code,
                "as_of": None,
                "source": self.source_label,
            }
        if item is None:
            return {
                "available": False,
                "status": "not_available",
                "drug_name": drug_name,
                "clinic_code": clinic_code,
                "as_of": None,
                "source": self.source_label,
            }
        data = item.as_dict(now=now, stale_after_minutes=self.stale_after_minutes)
        return {"available": data["status"] == "in_stock", **data}

    async def list(self, *, query: str | None, clinic_code: str | None) -> list[dict[str, Any]]:
        from sahyog_common.stock import search

        now = dt.datetime.now(dt.UTC)
        try:
            items = search(await self._load(), query=query, clinic_code=clinic_code)
        except StockUnavailable:
            return []
        return [
            item.as_dict(now=now, stale_after_minutes=self.stale_after_minutes) for item in items
        ]
