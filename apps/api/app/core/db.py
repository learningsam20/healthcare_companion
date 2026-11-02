from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None
        self._settings = settings

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            if not self._settings.database_url:
                raise RuntimeError("DATABASE_URL is not configured")
            self._engine = create_async_engine(
                self._settings.database_url,
                pool_size=self._settings.database_pool_size,
                max_overflow=self._settings.database_pool_overflow,
                pool_pre_ping=True,
            )
            self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        if self._sessionmaker is None:
            _ = self.engine
        assert self._sessionmaker is not None
        return self._sessionmaker

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None


async def prepare_audit_tip(session: "AsyncSession") -> None:
    """Load the durable audit hash tip once per session (ADR-14 continuity)."""
    if "audit_tip" in session.info:
        return
    from sqlalchemy import select

    from app.repositories.models import AuditEvent

    tip = await session.scalar(
        select(AuditEvent.event_hash)
        .where(AuditEvent.event_hash.is_not(None))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    session.info["audit_tip"] = tip


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    services = request.app.state.services
    async with services.db.sessionmaker() as session:
        try:
            await prepare_audit_tip(session)
        except Exception:  # noqa: BLE001 — tip load must never block the request
            session.info.setdefault("audit_tip", None)
        yield session
