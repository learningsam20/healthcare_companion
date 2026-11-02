from __future__ import annotations

from typing import Any, Protocol


class DeliveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NotificationPort(Protocol):
    def configured(self, channel: str) -> bool: ...

    async def send(
        self,
        *,
        channel: str,
        address: str,
        subject: str,
        body: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str: ...


class FhirError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FhirGateway(Protocol):
    """Read-only FHIR R4 access for demographics, encounters, and document refs."""

    def configured(self) -> bool: ...

    async def get_patient(self, fhir_patient_id: str) -> dict[str, Any]: ...

    async def list_encounters(
        self, fhir_patient_id: str, *, count: int = 20
    ) -> list[dict[str, Any]]: ...

    async def list_document_references(
        self, fhir_patient_id: str, *, count: int = 20
    ) -> list[dict[str, Any]]: ...
