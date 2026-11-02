from __future__ import annotations

import httpx
import pytest
from app.core.config import Settings
from app.core.ports import FhirError
from app.integrations.fhir import HttpFhirAdapter, InMemoryFhirAdapter, _map_patient


def test_map_patient_display_name() -> None:
    mapped = _map_patient(
        {
            "resourceType": "Patient",
            "id": "example",
            "name": [{"family": "Chalmers", "given": ["Peter", "James"]}],
            "gender": "male",
            "birthDate": "1974-12-25",
            "identifier": [{"system": "urn:oid:1.2.3", "value": "12345"}],
        }
    )
    assert mapped["fhir_id"] == "example"
    assert mapped["display_name"] == "Peter James Chalmers"
    assert mapped["gender"] == "male"
    assert mapped["identifiers"][0]["value"] == "12345"


@pytest.mark.asyncio
async def test_in_memory_fhir_adapter() -> None:
    adapter = InMemoryFhirAdapter()
    adapter.put_patient(
        "p1",
        {
            "resourceType": "Patient",
            "id": "p1",
            "name": [{"text": "Priya Sharma"}],
            "gender": "female",
        },
    )
    adapter.put_encounters(
        "p1",
        [
            {
                "resourceType": "Encounter",
                "id": "e1",
                "status": "finished",
                "class": {"code": "AMB"},
                "period": {"start": "2026-10-01T10:00:00Z"},
            }
        ],
    )
    patient = await adapter.get_patient("p1")
    assert patient["display_name"] == "Priya Sharma"
    encounters = await adapter.list_encounters("p1")
    assert len(encounters) == 1
    assert encounters[0]["status"] == "finished"
    with pytest.raises(FhirError) as exc:
        await adapter.get_patient("missing")
    assert exc.value.code == "fhir_not_found"


@pytest.mark.asyncio
async def test_http_fhir_adapter_reads_patient(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        fhir_base_url="https://fhir.example.test/baseR4",
        fhir_timeout_seconds=5,
    )
    adapter = HttpFhirAdapter(settings)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/Patient/example")
        return httpx.Response(
            200,
            json={
                "resourceType": "Patient",
                "id": "example",
                "name": [{"text": "Example Patient"}],
            },
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.integrations.fhir.httpx.AsyncClient", fake_client)
    patient = await adapter.get_patient("example")
    assert patient["display_name"] == "Example Patient"


@pytest.mark.asyncio
async def test_http_fhir_adapter_unconfigured() -> None:
    adapter = HttpFhirAdapter(Settings(_env_file=None, app_env="test", fhir_base_url=""))
    with pytest.raises(FhirError) as exc:
        await adapter.get_patient("example")
    assert exc.value.code == "fhir_unconfigured"
