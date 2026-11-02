"""Cloud STT remains fail-closed unless ALLOW_CLOUD_STT and credentials are set."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sahyog_mcp_stt.main import _cloud_allowed, _transcribe_cloud, stt_status


@pytest.fixture(autouse=True)
def _clear_cloud_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ALLOW_CLOUD_STT",
        "STT_ADAPTER",
        "STT_CLOUD_BASE_URL",
        "STT_CLOUD_API_KEY",
        "STT_CLOUD_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.asyncio
async def test_cloud_disabled_without_allow_flag() -> None:
    assert _cloud_allowed() is False
    result = await _transcribe_cloud("http://example/audio.wav", "en-IN")
    assert result["status"] == "stt_unavailable"
    assert result["reason"] == "cloud_stt_disabled"
    assert result["transcript"] is None


@pytest.mark.asyncio
async def test_cloud_unconfigured_when_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_CLOUD_STT", "true")
    result = await _transcribe_cloud("http://example/audio.wav", "en-IN")
    assert result["status"] == "stt_unavailable"
    assert result["reason"] == "cloud_stt_unconfigured"


@pytest.mark.asyncio
async def test_stt_status_reports_cloud_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_ADAPTER", "cloud")
    monkeypatch.setenv("ALLOW_CLOUD_STT", "false")
    ctx = SimpleNamespace(trace_id="t1")
    status = await stt_status({}, ctx)  # type: ignore[arg-type]
    assert status["adapter"] == "cloud"
    assert status["cloud_allowed"] is False
    assert status["ready"] is False
