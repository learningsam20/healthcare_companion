from __future__ import annotations

import hashlib
import ipaddress
import uuid
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories.models import PatientExternalId

_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


class AbdmSandboxError(ValueError):
    pass


def _sandbox_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        raise AbdmSandboxError("ABDM sandbox is unconfigured")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise AbdmSandboxError("ABDM_SANDBOX_URL must be an HTTP(S) URL")
    try:
        address = ipaddress.ip_address(host)
        allowed = address.is_loopback or any(address in network for network in _PRIVATE_NETWORKS)
    except ValueError:
        # Local Compose stub hostnames (abdm-stub) and sandbox DNS are allowed.
        allowed = (
            host == "localhost"
            or host.endswith(".localhost")
            or host == "abdm-stub"
            or host.endswith(".internal")
            or ".sandbox." in host
            or host.endswith(".sandbox.abdm.gov.in")
        )
    if not allowed:
        raise AbdmSandboxError(
            "ABDM_SANDBOX_URL must use localhost, abdm-stub, a private IP, or *.sandbox.*"
        )
    return url


def opaque_external_id(value: str) -> str:
    normalized = value.strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}|last4:{normalized[-4:]}"


class AbdmSandboxClient:
    """Minimal sandbox client and opaque-link store. This is not certification."""

    certified = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = (
            _sandbox_base_url(settings.abdm_sandbox_url)
            if settings.abdm_sandbox_url.strip()
            else ""
        )

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    def _require_configured(self) -> str:
        if not self._base_url:
            raise AbdmSandboxError("ABDM sandbox is unconfigured")
        return self._base_url

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._settings.abdm_client_id:
            headers["X-Client-Id"] = self._settings.abdm_client_id
        if self._settings.abdm_client_secret:
            headers["X-Client-Secret"] = self._settings.abdm_client_secret
        return headers

    async def get_health(self) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self._settings.abdm_timeout_seconds) as client:
            response = await client.get(
                f"{self._require_configured()}/health", headers=self._headers()
            )
            response.raise_for_status()
            payload = dict(response.json())
            payload.setdefault("certified", False)
            return payload

    async def post_health(self) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self._settings.abdm_timeout_seconds) as client:
            response = await client.post(
                f"{self._require_configured()}/health", headers=self._headers(), json={}
            )
            response.raise_for_status()
            payload = dict(response.json())
            payload.setdefault("certified", False)
            return payload

    async def gateway_session(self) -> dict[str, object]:
        """Official-path: POST /api/hiecm/gateway/v3/sessions (stub or sandbox)."""
        base = self._require_configured()
        body = {
            "clientId": self._settings.abdm_client_id or "local-stub",
            "clientSecret": self._settings.abdm_client_secret or "local-stub",
        }
        async with httpx.AsyncClient(timeout=self._settings.abdm_timeout_seconds) as client:
            response = await client.post(
                f"{base}/api/hiecm/gateway/v3/sessions",
                headers=self._headers(),
                json=body,
            )
            response.raise_for_status()
            payload = dict(response.json())
            payload["certified"] = False
            return payload

    async def equality_index(self) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self._settings.abdm_timeout_seconds) as client:
            response = await client.get(
                f"{self._require_configured()}/stub/equality", headers=self._headers()
            )
            response.raise_for_status()
            payload = dict(response.json())
            payload["certified"] = False
            return payload

    async def link(
        self,
        session: AsyncSession,
        *,
        patient_id: uuid.UUID,
        system: str,
        value: str,
        created_by: str,
        purpose: str = "identity_linkage",
    ) -> PatientExternalId:
        self._require_configured()
        result = await session.execute(
            select(PatientExternalId).where(
                PatientExternalId.patient_id == patient_id,
                PatientExternalId.system == system,
            )
        )
        row = result.scalar_one_or_none()
        encoded = opaque_external_id(value)
        if row is None:
            row = PatientExternalId(
                patient_id=patient_id,
                system=system,
                value_enc=encoded,
                purpose=purpose,
                status="linked",
                created_by=created_by,
            )
            session.add(row)
        else:
            row.value_enc = encoded
            row.purpose = purpose
            row.status = "linked"
            row.created_by = created_by
        await session.flush()
        return row
