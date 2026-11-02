from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import UsageRecord


class UsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        purpose: str,
        model_alias: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        trace_id: str | None,
        session_id: uuid.UUID | None,
        traffic_class: str,
        gateway_request_id: str | None = None,
    ) -> UsageRecord:
        usage = UsageRecord(
            purpose=purpose,
            model_alias=model_alias,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            trace_id=trace_id,
            gateway_request_id=gateway_request_id,
            session_id=session_id,
            traffic_class=traffic_class,
        )
        self._session.add(usage)
        await self._session.flush()
        return usage

    async def summary(
        self, *, start: dt.datetime, end: dt.datetime, traffic_class: str = "real"
    ) -> dict[str, Any]:
        row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
                    func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                    func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                    func.count(UsageRecord.id),
                ).where(
                    UsageRecord.created_at >= start,
                    UsageRecord.created_at < end,
                    UsageRecord.traffic_class == traffic_class,
                )
            )
        ).one()
        return {
            "cost_usd": round(float(row[0]), 6),
            "prompt_tokens": int(row[1]),
            "completion_tokens": int(row[2]),
            "calls": int(row[3]),
        }

    async def by_purpose(
        self, *, start: dt.datetime, end: dt.datetime, traffic_class: str = "real"
    ) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(
                UsageRecord.purpose,
                UsageRecord.model_alias,
                func.count(UsageRecord.id),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
            )
            .where(
                UsageRecord.created_at >= start,
                UsageRecord.created_at < end,
                UsageRecord.traffic_class == traffic_class,
            )
            .group_by(UsageRecord.purpose, UsageRecord.model_alias)
            .order_by(func.sum(UsageRecord.cost_usd).desc())
        )
        return [
            {
                "purpose": row[0],
                "model_alias": row[1],
                "calls": int(row[2]),
                "prompt_tokens": int(row[3]),
                "completion_tokens": int(row[4]),
                "cost_usd": round(float(row[5]), 6),
            }
            for row in rows
        ]
