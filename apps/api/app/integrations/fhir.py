"""Read-only FHIR R4 HTTP adapter.

No writes, no subscriptions, no vendor SDK. Missing credentials fail closed as
unconfigured. OAuth client-credentials is used when FHIR_TOKEN_URL and client
secrets are set; otherwise the base URL is called without a bearer token (open
test servers only).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from app.core.config import Settings
from app.core.ports import FhirError, FhirGateway


def _display_name(resource: dict[str, Any]) -> str | None:
    names = resource.get("name") or []
    if not isinstance(names, list) or not names:
        return None
    first = names[0] if isinstance(names[0], dict) else {}
    if first.get("text"):
        return str(first["text"])
    given = " ".join(str(item) for item in first.get("given") or [])
    family = str(first.get("family") or "")
    combined = " ".join(part for part in (given, family) if part).strip()
    return combined or None


def _map_patient(resource: dict[str, Any]) -> dict[str, Any]:
    return {
        "fhir_id": str(resource.get("id") or ""),
        "resource_type": "Patient",
        "display_name": _display_name(resource),
        "gender": resource.get("gender"),
        "birth_date": resource.get("birthDate"),
        "active": resource.get("active"),
        "identifiers": [
            {
                "system": item.get("system"),
                "value": item.get("value"),
            }
            for item in resource.get("identifier") or []
            if isinstance(item, dict)
        ],
    }


def _map_encounter(resource: dict[str, Any]) -> dict[str, Any]:
    period = resource.get("period") if isinstance(resource.get("period"), dict) else {}
    return {
        "fhir_id": str(resource.get("id") or ""),
        "resource_type": "Encounter",
        "status": resource.get("status"),
        "class_code": (
            (resource.get("class") or {}).get("code")
            if isinstance(resource.get("class"), dict)
            else None
        ),
        "type": [
            coding.get("display") or coding.get("code")
            for item in resource.get("type") or []
            if isinstance(item, dict)
            for coding in item.get("coding") or []
            if isinstance(coding, dict)
        ],
        "period_start": period.get("start"),
        "period_end": period.get("end"),
    }


def _map_document_reference(resource: dict[str, Any]) -> dict[str, Any]:
    """Normalize DocumentReference into a stable UI/API shape."""
    type_display: str | None = None
    type_field = resource.get("type")
    if isinstance(type_field, dict):
        for coding in type_field.get("coding") or []:
            if isinstance(coding, dict) and (coding.get("display") or coding.get("code")):
                type_display = str(coding.get("display") or coding.get("code"))
                break
        if not type_display and type_field.get("text"):
            type_display = str(type_field["text"])
    description = resource.get("description")
    content_types: list[str] = []
    for item in resource.get("content") or []:
        if not isinstance(item, dict):
            continue
        attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else {}
        ctype = attachment.get("contentType")
        if ctype:
            content_types.append(str(ctype))
    return {
        "fhir_id": str(resource.get("id") or ""),
        "resource_type": "DocumentReference",
        "status": resource.get("status"),
        "doc_status": resource.get("docStatus"),
        "type": type_display,
        "description": str(description) if description else None,
        "date": resource.get("date"),
        "content_types": content_types,
        "source": "fhir",
    }


def local_document_as_reference(document: Any) -> dict[str, Any]:
    """Project a Sahyog Document row into the same shape as FHIR DocumentReference."""
    created = getattr(document, "created_at", None)
    date_value = created.isoformat() if hasattr(created, "isoformat") else created
    return {
        "fhir_id": str(getattr(document, "id", "")),
        "resource_type": "DocumentReference",
        "status": "current",
        "doc_status": str(getattr(document, "status", "") or ""),
        "type": str(getattr(document, "kind", "") or "other"),
        "description": str(getattr(document, "title", "") or ""),
        "date": date_value,
        "content_types": [str(getattr(document, "content_type", "") or "application/pdf")],
        "source": "local",
        "local_document_id": str(getattr(document, "id", "")),
        "page_count": getattr(document, "page_count", None),
        "size_bytes": getattr(document, "size_bytes", None),
    }


class HttpFhirAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._token: str | None = None
        self._token_expires_at = 0.0

    def configured(self) -> bool:
        return self._settings.fhir_configured

    def _auth_required(self) -> bool:
        return bool(
            self._settings.fhir_client_id
            and self._settings.fhir_client_secret
            and self._settings.fhir_token_url
        )

    async def _access_token(self, client: httpx.AsyncClient) -> str | None:
        if not self._auth_required():
            return None
        now = time.monotonic()
        if self._token and now < self._token_expires_at - 30:
            return self._token
        response = await client.post(
            self._settings.fhir_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.fhir_client_id,
                "client_secret": self._settings.fhir_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise FhirError("fhir_auth_failed")
        expires_in = float(payload.get("expires_in") or 300)
        self._token = token
        self._token_expires_at = now + expires_in
        return token

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured():
            raise FhirError("fhir_unconfigured")
        base = self._settings.fhir_base_url.rstrip("/")
        timeout = self._settings.fhir_timeout_seconds
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                headers = {"Accept": "application/fhir+json"}
                token = await self._access_token(client)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                response = await client.get(f"{base}/{path.lstrip('/')}", params=params, headers=headers)
                if response.status_code == 404:
                    raise FhirError("fhir_not_found")
                response.raise_for_status()
                payload = response.json()
        except FhirError:
            raise
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise FhirError("fhir_unavailable") from exc
        if not isinstance(payload, dict):
            raise FhirError("fhir_invalid_response")
        return payload

    async def get_patient(self, fhir_patient_id: str) -> dict[str, Any]:
        resource = await self._get_json(f"Patient/{fhir_patient_id}")
        if resource.get("resourceType") != "Patient":
            raise FhirError("fhir_invalid_response")
        return _map_patient(resource)

    async def list_encounters(
        self, fhir_patient_id: str, *, count: int = 20
    ) -> list[dict[str, Any]]:
        bundle = await self._get_json(
            "Encounter",
            params={"patient": fhir_patient_id, "_count": str(max(1, min(count, 50)))},
        )
        if bundle.get("resourceType") != "Bundle":
            raise FhirError("fhir_invalid_response")
        encounters: list[dict[str, Any]] = []
        for entry in bundle.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            resource = entry.get("resource")
            if isinstance(resource, dict) and resource.get("resourceType") == "Encounter":
                encounters.append(_map_encounter(resource))
        return encounters

    async def list_document_references(
        self, fhir_patient_id: str, *, count: int = 20
    ) -> list[dict[str, Any]]:
        bundle = await self._get_json(
            "DocumentReference",
            params={"patient": fhir_patient_id, "_count": str(max(1, min(count, 50)))},
        )
        if bundle.get("resourceType") != "Bundle":
            raise FhirError("fhir_invalid_response")
        docs: list[dict[str, Any]] = []
        for entry in bundle.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            resource = entry.get("resource")
            if isinstance(resource, dict) and resource.get("resourceType") == "DocumentReference":
                docs.append(_map_document_reference(resource))
        return docs


class InMemoryFhirAdapter:
    """Test double only. Never selected as a runtime mock."""

    def __init__(self, patients: dict[str, dict[str, Any]] | None = None) -> None:
        self._patients = patients or {}
        self._encounters: dict[str, list[dict[str, Any]]] = {}
        self._document_references: dict[str, list[dict[str, Any]]] = {}

    def configured(self) -> bool:
        return True

    def put_patient(self, fhir_id: str, resource: dict[str, Any]) -> None:
        self._patients[fhir_id] = resource

    def put_encounters(self, fhir_patient_id: str, encounters: list[dict[str, Any]]) -> None:
        self._encounters[fhir_patient_id] = encounters

    def put_document_references(
        self, fhir_patient_id: str, documents: list[dict[str, Any]]
    ) -> None:
        self._document_references[fhir_patient_id] = documents

    async def get_patient(self, fhir_patient_id: str) -> dict[str, Any]:
        resource = self._patients.get(fhir_patient_id)
        if resource is None:
            raise FhirError("fhir_not_found")
        return _map_patient(resource)

    async def list_encounters(
        self, fhir_patient_id: str, *, count: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._encounters.get(fhir_patient_id, [])
        return [_map_encounter(item) for item in rows[:count]]

    async def list_document_references(
        self, fhir_patient_id: str, *, count: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._document_references.get(fhir_patient_id, [])
        return [_map_document_reference(item) for item in rows[:count]]


def build_fhir_gateway(settings: Settings) -> FhirGateway | None:
    if not settings.fhir_configured:
        return None
    return HttpFhirAdapter(settings)
