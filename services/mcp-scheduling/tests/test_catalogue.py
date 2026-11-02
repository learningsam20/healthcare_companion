from fastapi.testclient import TestClient

from sahyog_mcp_scheduling.main import app


def test_scheduling_catalogue_lists_booking_tools() -> None:
    client = TestClient(app)
    response = client.get("/tools")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["tools"]}
    assert {
        "search_doctors",
        "get_availability",
        "hold_slot",
        "confirm_booking",
        "cancel_appointment",
        "reschedule_appointment",
        "get_appointment",
    } <= names
