"""G-09: /meta must never report ABDM as certified, whatever the configuration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.modules.meta.router import _adapters


class _Features:
    def __init__(self, enabled: set[str]) -> None:
        self._enabled = enabled

    def enabled(self, key: str) -> bool:
        return key in self._enabled


@pytest.mark.parametrize(
    ("features", "url", "expected_status"),
    [
        (set(), "", "disabled"),
        ({"abdm_link"}, "", "unconfigured"),
        ({"abdm_link"}, "http://abdm-stub:8090", "configured"),
    ],
)
def test_abdm_adapter_is_never_certified(
    features: set[str], url: str, expected_status: str
) -> None:
    services = SimpleNamespace(
        settings=Settings(_env_file=None, app_env="test", abdm_sandbox_url=url),
        features=_Features(features),
    )
    adapter = _adapters(services)["abdm_sandbox"]  # type: ignore[arg-type]
    assert adapter["status"] == expected_status
    assert adapter["certified"] is False


@pytest.mark.parametrize(
    ("features", "expected"), [(set(), "disabled"), ({"external_mcp"}, "enabled")]
)
def test_external_mcp_kill_switch_visible_and_uncertified(
    features: set[str], expected: str
) -> None:
    services = SimpleNamespace(
        settings=Settings(_env_file=None, app_env="test"),
        features=_Features(features),
    )
    adapter = _adapters(services)["external_mcp"]  # type: ignore[arg-type]
    assert adapter["status"] == expected
    assert adapter["mode"] == "read_only"
    assert adapter["certified"] is False
    assert "EXTERNAL_MCP_ENABLED" in adapter["kill_switch"]
