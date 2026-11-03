"""Pharmacy stock_items repository."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

from app.repositories.models import StockImport, StockItemRecord
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession


class StockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        query: str | None,
        clinic_code: str | None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[StockItemRecord], int]:
        conditions = []
        if clinic_code:
            conditions.append(StockItemRecord.clinic_code == clinic_code)
        if query:
            needle = f"%{query.strip().casefold()}%"
            conditions.append(
                or_(
                    func.lower(StockItemRecord.drug_name).like(needle),
                    func.lower(StockItemRecord.sku).like(needle),
                    func.lower(StockItemRecord.form).like(needle),
                    func.lower(StockItemRecord.strength).like(needle),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(StockItemRecord).where(*conditions)
        )
        rows = await self._session.scalars(
            select(StockItemRecord)
            .where(*conditions)
            .order_by(StockItemRecord.drug_name.asc(), StockItemRecord.clinic_code.asc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def get(self, item_id: uuid.UUID) -> StockItemRecord | None:
        return await self._session.get(StockItemRecord, item_id)

    async def find(
        self, *, drug_name: str, clinic_code: str
    ) -> StockItemRecord | None:
        return await self._session.scalar(
            select(StockItemRecord).where(
                StockItemRecord.clinic_code == clinic_code,
                func.lower(StockItemRecord.drug_name) == drug_name.strip().casefold(),
            )
        )

    async def match_terms(
        self, terms: list[str], *, clinic_code: str | None, limit: int = 80
    ) -> list[StockItemRecord]:
        needles: list[str] = []
        seen: set[str] = set()
        for term in terms:
            needle = term.strip().casefold().replace("%", "").replace("_", "")
            if len(needle) < 3 or needle in seen:
                continue
            seen.add(needle)
            needles.append(needle)
            if len(needles) >= 24:
                break
        if not needles:
            return []
        likes = [
            func.lower(StockItemRecord.drug_name).like(f"%{needle}%") for needle in needles
        ]
        matched = select(StockItemRecord).where(or_(*likes))
        if clinic_code:
            at_clinic = await self._session.scalars(
                matched.where(StockItemRecord.clinic_code == clinic_code)
                .order_by(func.length(StockItemRecord.drug_name))
                .limit(limit)
            )
            rows = list(at_clinic)
            if rows:
                return rows
        anywhere = await self._session.scalars(
            matched.order_by(func.length(StockItemRecord.drug_name)).limit(limit)
        )
        return list(anywhere)

    async def find_best(
        self, *, drug_name: str, clinic_code: str
    ) -> StockItemRecord | None:
        exact = await self.find(drug_name=drug_name, clinic_code=clinic_code)
        if exact is not None:
            return exact
        needle = drug_name.strip().casefold()
        if len(needle) < 4:
            return None
        rows = await self.match_terms([needle], clinic_code=clinic_code, limit=20)
        best: StockItemRecord | None = None
        best_score = -1
        for row in rows:
            words = row.drug_name.casefold().split()
            if not words:
                continue
            if words[0] == needle or words[0].startswith(needle):
                score = 80
            elif any(word.startswith(needle) for word in words):
                score = 45
            else:
                continue
            score -= len(row.drug_name) // 20
            if score > best_score:
                best_score = score
                best = row
        return best if best_score >= 45 else None

    async def upsert(self, item: StockItemRecord) -> StockItemRecord:
        existing = await self._session.scalar(
            select(StockItemRecord).where(
                StockItemRecord.clinic_code == item.clinic_code,
                StockItemRecord.sku == item.sku,
            )
        )
        if existing is None:
            self._session.add(item)
            await self._session.flush()
            return item
        existing.drug_name = item.drug_name
        existing.form = item.form
        existing.strength = item.strength
        existing.quantity = item.quantity
        existing.updated_at = item.updated_at
        existing.source = item.source
        await self._session.flush()
        return existing

    async def delete(self, item_id: uuid.UUID) -> bool:
        row = await self.get(item_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def all_items(self) -> list[StockItemRecord]:
        rows = await self._session.scalars(select(StockItemRecord))
        return list(rows)

    async def record_import(
        self,
        *,
        source: str,
        raw: bytes,
        as_of: dt.datetime,
        row_count: int,
        status: str,
        errors: list[Any],
    ) -> StockImport:
        record = StockImport(
            source=source,
            file_hash=hashlib.sha256(raw).hexdigest(),
            as_of=as_of,
            row_count=row_count,
            status=status,
            errors=errors,
        )
        self._session.add(record)
        await self._session.flush()
        return record
