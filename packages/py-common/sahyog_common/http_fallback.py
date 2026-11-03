"""Try the in-network API first, then the published host port.

Compose services call ``http://api:8000``. A host-side API (``--local``) owns
that published port instead, so MCP containers retry ``SAHYOG_API_URL_FALLBACK``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


def api_bases() -> list[str]:
    primary = os.environ.get("SAHYOG_API_URL", "http://api:8000").strip().rstrip("/")
    fallback = os.environ.get(
        "SAHYOG_API_URL_FALLBACK", "http://host.docker.internal:5706"
    ).strip().rstrip("/")
    bases: list[str] = []
    for item in (primary, fallback):
        if item and item not in bases:
            bases.append(item)
    return bases


def candidate_urls(url: str) -> list[str]:
    """Keep a configured URL, and rewrite an ``api`` hostname onto the fallback origin."""
    cleaned = url.strip()
    urls = [cleaned] if cleaned else []
    fallback = os.environ.get(
        "SAHYOG_API_URL_FALLBACK", "http://host.docker.internal:5706"
    ).strip().rstrip("/")
    if not cleaned or not fallback:
        return urls
    parsed = urlsplit(cleaned)
    if parsed.hostname != "api":
        return urls
    origin = urlsplit(fallback)
    rewritten = urlunsplit((origin.scheme, origin.netloc, parsed.path, "", ""))
    if rewritten not in urls:
        urls.append(rewritten)
    return urls


async def request_first(
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
) -> httpx.Response:
    bases = api_bases()
    last_error: Exception | None = None
    for index, base in enumerate(bases):
        url = f"{base}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    params=dict(params) if params else None,
                    json=json_body,
                    headers=dict(headers) if headers else None,
                )
        except httpx.HTTPError as exc:
            last_error = exc
            continue
        if response.status_code >= 500 and index < len(bases) - 1:
            last_error = httpx.HTTPStatusError(
                f"{response.status_code} from {url}",
                request=response.request,
                response=response,
            )
            continue
        return response
    if last_error is not None:
        raise last_error
    raise httpx.HTTPError("No Sahyog API base is configured")
