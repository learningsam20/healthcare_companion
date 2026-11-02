from fastapi.testclient import TestClient

from sahyog_mcp_records.main import app


def test_records_catalogue_lists_search_tools() -> None:
    client = TestClient(app)
    response = client.get("/tools")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["tools"]}
    assert {
        "list_documents",
        "get_document_status",
        "search_records",
        "get_document_chunk",
        "list_medications",
    } <= names
