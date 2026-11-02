"""External MCP read-only demo listener (G-14 / ADR-19).

Partners call a small allowlisted tool surface with a signed Sahyog context.
Writes are rejected. Kill switch: FEATURE / EXTERNAL_MCP_ENABLED=false returns empty catalogue.

Versioning and per-consumer quotas come from ``config/external_mcp.yaml`` (override the
path with ``EXTERNAL_MCP_CONFIG``). Quotas are an in-process sliding window per signed
actor and per replica; they are an interim control, not partner productisation.
"""

from __future__ import annotations

import inspect
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import yaml
from sahyog_common.context import ExecutionContext
from sahyog_common.files import config_dir, load_yaml
from sahyog_common.mcp_service import ToolRateLimited, create_mcp_app

API_BASE = os.environ.get("SAHYOG_API_URL", "http://api:8000").rstrip("/")
API_KEY = os.environ.get("INTERNAL_API_KEY") or os.environ.get("STOCK_API_KEY") or ""


DEFAULT_CONTRACT: dict[str, Any] = {
    "api_version": "v1",
    "supported_versions": ["v1"],
    "quota": {"default": {"requests_per_minute": 30}, "consumers": {}},
    "tools": {},
}


def load_contract() -> dict[str, Any]:
    """Load versioning/quota config; fall back to safe defaults and say so."""
    path = Path(os.environ.get("EXTERNAL_MCP_CONFIG") or config_dir() / "external_mcp.yaml")
    try:
        data = load_yaml(path)
    except (OSError, ValueError, yaml.YAMLError):
        return {**DEFAULT_CONTRACT, "source": "defaults"}
    return {**DEFAULT_CONTRACT, **data, "source": "file"}


class QuotaLimiter:
    """Sliding-window requests-per-minute limiter keyed by signed actor subject."""

    def __init__(
        self,
        *,
        default_rpm: int,
        consumers: dict[str, int] | None = None,
        clock: Callable[[], float] = time.monotonic,
        window_seconds: float = 60.0,
    ) -> None:
        self._default = max(1, int(default_rpm))
        self._consumers = {k: max(1, int(v)) for k, v in (consumers or {}).items()}
        self._clock = clock
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    @classmethod
    def from_contract(cls, contract: dict[str, Any]) -> QuotaLimiter:
        quota = contract.get("quota") or {}
        consumers = {
            str(name): int((cfg or {}).get("requests_per_minute", 0) or 0)
            for name, cfg in (quota.get("consumers") or {}).items()
        }
        default = int((quota.get("default") or {}).get("requests_per_minute", 30))
        return cls(default_rpm=default, consumers={k: v for k, v in consumers.items() if v})

    def limit_for(self, consumer: str) -> int:
        return self._consumers.get(consumer, self._default)

    def check(self, consumer: str) -> None:
        now = self._clock()
        hits = self._hits[consumer]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self.limit_for(consumer):
            raise ToolRateLimited(retry_after=int(self._window - (now - hits[0])) + 1)
        hits.append(now)


CONTRACT = load_contract()
LIMITER = QuotaLimiter.from_contract(CONTRACT)


def _limited(handler: Callable[..., Any]) -> Callable[..., Any]:
    async def wrapped(args: dict[str, Any], context: ExecutionContext) -> Any:
        LIMITER.check(context.actor_subject)
        result = handler(args, context)
        if inspect.isawaitable(result):
            result = await result
        return result

    wrapped.__name__ = handler.__name__
    return wrapped


def _enabled() -> bool:
    return os.environ.get("EXTERNAL_MCP_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _headers() -> dict[str, str]:
    return {
        "X-Internal-Api-Key": API_KEY,
        "X-Stock-Api-Key": API_KEY,
        "Accept": "application/json",
    }


async def search_doctors(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    if not _enabled():
        raise ValueError("external_mcp_disabled")
    params: dict[str, Any] = {"limit": int(args.get("limit") or 3)}
    if args.get("specialty_code"):
        params["specialty"] = str(args["specialty_code"])
    if args.get("clinic_code"):
        params["clinic_code"] = str(args["clinic_code"])
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{API_BASE}/api/v1/internal/scheduling/doctors",
            params=params,
            headers=_headers(),
        )
        response.raise_for_status()
        doctors = response.json()
    return {"doctors": doctors if isinstance(doctors, list) else [], "mode": "external_readonly"}


async def get_stock_status(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    if not _enabled():
        raise ValueError("external_mcp_disabled")
    drug = args.get("drug_name")
    clinic = args.get("clinic_code")
    if not drug or not clinic:
        raise ValueError("drug_name and clinic_code are required")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{API_BASE}/api/v1/pharmacy/stock/lookup",
            params={"drug_name": str(drug), "clinic_code": str(clinic)},
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()


async def ping(args: dict[str, Any], context: ExecutionContext) -> dict[str, Any]:
    return {
        "ok": _enabled(),
        "mode": "read_only",
        "actor": context.actor_subject,
        "trace_id": context.trace_id,
    }


TOOLS: dict[str, tuple[Any, str]] = {}
if _enabled():
    TOOLS = {
        "ping": (_limited(ping), "Liveness probe for external MCP consumers"),
        "search_doctors": (_limited(search_doctors), "Read-only doctor shortlist"),
        "get_stock_status": (_limited(get_stock_status), "Read-only pharmacy stock lookup"),
    }

app = create_mcp_app(
    "external",
    TOOLS,
    api_version=str(CONTRACT["api_version"]),
    supported_versions=tuple(str(v) for v in CONTRACT["supported_versions"]),
    catalogue_extra={
        "kill_switch": {"enabled": _enabled(), "env": "EXTERNAL_MCP_ENABLED"},
        "quota": {
            "requests_per_minute_default": LIMITER.limit_for(""),
            "scope": "per_actor_per_replica",
        },
        "tool_versions": {
            name: (CONTRACT.get("tools") or {}).get(name, {}).get("version")
            for name in sorted(TOOLS)
        },
        "contract_source": CONTRACT["source"],
        "read_only": True,
        "certified": False,
    },
)
