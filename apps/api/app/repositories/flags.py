from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import FeatureFlagChange, FeatureFlagOverride


class FeatureFlagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        flag_key: str,
        old_value: bool,
        new_value: bool,
        actor_subject: str,
        reason: str,
    ) -> FeatureFlagChange:
        change = FeatureFlagChange(
            flag_key=flag_key,
            old_value=old_value,
            new_value=new_value,
            actor_subject=actor_subject,
            reason=reason,
        )
        self._session.add(change)
        await self._session.flush()
        return change

    async def recent(self, limit: int = 50) -> list[FeatureFlagChange]:
        rows = await self._session.scalars(
            select(FeatureFlagChange).order_by(FeatureFlagChange.created_at.desc()).limit(limit)
        )
        return list(rows)

    async def overrides(self) -> dict[str, bool]:
        rows = await self._session.scalars(select(FeatureFlagOverride))
        return {row.flag_key: row.value for row in rows}

    async def upsert_override(
        self, *, flag_key: str, value: bool, updated_by: str
    ) -> FeatureFlagOverride:
        override = await self._session.get(FeatureFlagOverride, flag_key)
        if override is None:
            override = FeatureFlagOverride(flag_key=flag_key, value=value, updated_by=updated_by)
            self._session.add(override)
        else:
            override.value = value
            override.updated_by = updated_by
        await self._session.flush()
        return override
