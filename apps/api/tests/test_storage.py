from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.storage import DocumentStorage


class _FakeS3:
    def __init__(self, endpoint: str = "http://minio:9000") -> None:
        self.endpoint = endpoint

    def generate_presigned_url(self, operation: str, Params: dict[str, Any], ExpiresIn: int) -> str:
        assert operation == "put_object"
        assert Params["Bucket"] == "sahyog-audio"
        assert ExpiresIn == 300
        return f"{self.endpoint}/sahyog-audio/audio/key.wav?X-Amz-Signature=abc"


class _PutS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _storage(**overrides: Any) -> DocumentStorage:
    values: dict[str, Any] = {
        "s3_endpoint_url": "http://minio:9000",
        "s3_public_endpoint_url": "",
        "s3_access_key": "test-key",
        "s3_secret_key": "test-secret",
    }
    values.update(overrides)
    # _env_file=None keeps the developer's local .env out of unit-test expectations.
    settings = Settings(_env_file=None, **values)
    return DocumentStorage(settings)


async def test_presign_keeps_internal_host_without_public_endpoint() -> None:
    storage = _storage()
    storage._presign_client = _FakeS3()
    url = await storage.presign_put(
        key="audio/key.wav", content_type="audio/wav", bucket="sahyog-audio"
    )
    assert url.startswith("http://minio:9000/")


async def test_presign_signs_against_the_public_endpoint() -> None:
    storage = _storage(s3_public_endpoint_url="https://storage.care.example.invalid")
    built: list[str] = []

    def build(endpoint: str) -> _FakeS3:
        built.append(endpoint)
        return _FakeS3(endpoint)

    storage._build_client = build  # type: ignore[method-assign]
    url = await storage.presign_put(
        key="audio/key.wav", content_type="audio/wav", bucket="sahyog-audio"
    )
    # SigV4 includes the Host header, so swapping hosts after signing breaks the
    # signature. The public host must be the one boto3 signs.
    assert built == ["https://storage.care.example.invalid"]
    assert urlsplit(url).netloc == "storage.care.example.invalid"
    assert "X-Amz-Signature=abc" in url


async def test_real_presigner_uses_public_host() -> None:
    storage = _storage(s3_public_endpoint_url="https://storage.care.example.invalid")
    url = await storage.presign_put(
        key="audio/key.wav", content_type="audio/wav", bucket="sahyog-audio"
    )
    parsed = urlsplit(url)
    assert parsed.netloc == "storage.care.example.invalid"
    assert "X-Amz-Signature=" in parsed.query


async def test_put_omits_sse_when_the_store_has_no_kms() -> None:
    storage = _storage()
    client = _PutS3()
    storage._client = client
    await storage.put(key="documents/key.pdf", data=b"%PDF", content_type="application/pdf")
    assert client.calls[0]["Bucket"] == "sahyog-documents"
    assert "ServerSideEncryption" not in client.calls[0]


async def test_put_sends_sse_when_configured() -> None:
    storage = _storage(s3_server_side_encryption="AES256")
    client = _PutS3()
    storage._client = client
    await storage.put(key="documents/key.pdf", data=b"%PDF", content_type="application/pdf")
    assert client.calls[0]["ServerSideEncryption"] == "AES256"
