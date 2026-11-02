"""HTTP client for self-hosted Mem0 (Docker stack).

Uses the REST API from https://mem0.ai/library/integrations/self-host-mem0-docker.
Falls closed when MEM0_URL is unset or the service is down — preference table remains.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings


class Mem0Unavailable(RuntimeError):
    pass


class Mem0Client:
    def __init__(self, settings: Settings) -> None:
        self._base = (getattr(settings, "mem0_url", "") or "").rstrip("/")
        self._timeout = float(getattr(settings, "mem0_timeout_seconds", 15.0) or 15.0)
        self._api_key = (getattr(settings, "mem0_api_key", "") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self._base)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def add(
        self,
        *,
        user_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise Mem0Unavailable("mem0_unconfigured")
        payload: dict[str, Any] = {
            "messages": [{"role": "user", "content": text}],
            "user_id": user_id,
        }
        if metadata:
            payload["metadata"] = metadata
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/memories",
                    json=payload,
                    headers=self._headers(),
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Mem0Unavailable(f"mem0_add_failed:{exc}") from exc

    async def search(self, *, user_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if not self.configured:
            raise Mem0Unavailable("mem0_unconfigured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/search",
                    json={"query": query, "user_id": user_id, "limit": limit},
                    headers=self._headers(),
                )
                # Some builds use GET /memories?user_id=
                if response.status_code == 404:
                    response = await client.get(
                        f"{self._base}/memories",
                        params={"user_id": user_id},
                        headers=self._headers(),
                    )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Mem0Unavailable(f"mem0_search_failed:{exc}") from exc
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("results", "memories", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    async def list_for_user(self, *, user_id: str) -> list[dict[str, Any]]:
        if not self.configured:
            raise Mem0Unavailable("mem0_unconfigured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base}/memories",
                    params={"user_id": user_id},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise Mem0Unavailable(f"mem0_list_failed:{exc}") from exc
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data["results"]
        return []

    async def delete(self, *, memory_id: str) -> None:
        if not self.configured:
            raise Mem0Unavailable("mem0_unconfigured")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.delete(
                    f"{self._base}/memories/{memory_id}",
                    headers=self._headers(),
                )
                if response.status_code not in {200, 204, 404}:
                    response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise Mem0Unavailable(f"mem0_delete_failed:{exc}") from exc
