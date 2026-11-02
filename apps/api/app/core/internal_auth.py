"""Shared secret auth for MCP → API internal tool endpoints."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_internal_api_key(
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-Api-Key"),
    x_stock_api_key: str | None = Header(default=None, alias="X-Stock-Api-Key"),
) -> None:
    settings = get_settings()
    expected = settings.resolved_internal_api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API key is not configured",
        )
    provided = (x_internal_api_key or x_stock_api_key or "").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )
