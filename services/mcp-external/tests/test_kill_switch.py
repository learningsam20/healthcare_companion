"""External MCP kill-switch and read-only surface (G-14)."""

from __future__ import annotations

import inspect

import pytest


class _FakeContext:
    actor_subject = "test"
    trace_id = "t"


@pytest.mark.asyncio
async def test_disabled_ping_reports_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "false")
    from sahyog_mcp_external import main as mod

    assert mod._enabled() is False
    result = mod.ping({}, _FakeContext())
    if inspect.isawaitable(result):
        result = await result
    assert result["ok"] is False
    assert result["mode"] == "read_only"


@pytest.mark.asyncio
async def test_search_rejected_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "false")
    from sahyog_mcp_external import main as mod

    with pytest.raises(ValueError, match="external_mcp_disabled"):
        await mod.search_doctors({"limit": 1}, _FakeContext())


@pytest.mark.asyncio
async def test_stock_rejected_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTERNAL_MCP_ENABLED", "false")
    from sahyog_mcp_external import main as mod

    with pytest.raises(ValueError, match="external_mcp_disabled"):
        await mod.get_stock_status(
            {"drug_name": "pcm", "clinic_code": "C1"}, _FakeContext()
        )
