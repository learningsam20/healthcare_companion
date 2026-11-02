"""S3-compatible object storage. The bucket layout is opaque to callers."""

from __future__ import annotations

import asyncio
from typing import Any

import boto3
from botocore.config import Config

from app.core.config import Settings


class StorageError(RuntimeError):
    pass


class DocumentStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None
        self._presign_client: Any | None = None

    def _build_client(self, endpoint_url: str) -> Any:
        if not self._settings.s3_configured:
            raise StorageError("S3 is not configured")
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=self._settings.s3_region,
            aws_access_key_id=self._settings.s3_access_key,
            aws_secret_access_key=self._settings.s3_secret_key,
            config=Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": ("path" if self._settings.s3_use_path_style else "virtual")
                },
                retries={"max_attempts": 3, "mode": "standard"},
                # S3Proxy rejects flexible checksum headers (x-amz-checksum-crc32).
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def _s3(self) -> Any:
        if self._client is None:
            self._client = self._build_client(self._settings.s3_endpoint_url)
        return self._client

    def _presigner(self) -> Any:
        # SigV4 signs the Host header, so a browser-facing URL must be signed
        # against the public host rather than having the host swapped afterwards.
        if self._presign_client is None:
            public = self._settings.s3_public_endpoint_url.strip()
            endpoint = public or self._settings.s3_endpoint_url
            self._presign_client = self._build_client(endpoint)
        return self._presign_client

    async def put(
        self, *, key: str, data: bytes, content_type: str, bucket: str | None = None
    ) -> None:
        target = bucket or self._settings.s3_bucket_documents

        def _put() -> None:
            request: dict[str, Any] = {
                "Bucket": target,
                "Key": key,
                "Body": data,
                "ContentType": content_type,
            }
            # MinIO rejects SSE-S3 unless a KMS is configured, so this stays opt-in.
            if self._settings.s3_server_side_encryption:
                request["ServerSideEncryption"] = self._settings.s3_server_side_encryption
            self._s3().put_object(**request)

        try:
            await asyncio.to_thread(_put)
        except Exception as exc:
            raise StorageError("object storage write failed") from exc

    async def get(self, *, key: str, bucket: str | None = None) -> bytes:
        target = bucket or self._settings.s3_bucket_documents

        def _get() -> bytes:
            response = self._s3().get_object(Bucket=target, Key=key)
            return response["Body"].read()  # type: ignore[no-any-return]

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            raise StorageError("object storage read failed") from exc

    async def presign_put(
        self,
        *,
        key: str,
        content_type: str,
        bucket: str | None = None,
        expires_seconds: int = 300,
    ) -> str:
        target = bucket or self._settings.s3_bucket_documents

        def _sign() -> str:
            return str(
                self._presigner().generate_presigned_url(
                    "put_object",
                    Params={"Bucket": target, "Key": key, "ContentType": content_type},
                    ExpiresIn=expires_seconds,
                )
            )

        try:
            return await asyncio.to_thread(_sign)
        except Exception as exc:
            raise StorageError("object storage presign failed") from exc

    async def presign_get(
        self, *, key: str, bucket: str | None = None, expires_seconds: int = 300
    ) -> str:
        target = bucket or self._settings.s3_bucket_documents

        def _sign() -> str:
            return str(
                self._presigner().generate_presigned_url(
                    "get_object",
                    Params={"Bucket": target, "Key": key},
                    ExpiresIn=expires_seconds,
                )
            )

        try:
            return await asyncio.to_thread(_sign)
        except Exception as exc:
            raise StorageError("object storage presign failed") from exc

    async def presign_get_internal(
        self, *, key: str, bucket: str | None = None, expires_seconds: int = 300
    ) -> str:
        """Presigned GET against the *internal* endpoint, for service-to-service fetches.

        mcp-stt runs on the Compose network and cannot reach the browser-facing
        public endpoint, so scribe hands it a URL signed for the internal host.
        """
        target = bucket or self._settings.s3_bucket_documents

        def _sign() -> str:
            return str(
                self._s3().generate_presigned_url(
                    "get_object",
                    Params={"Bucket": target, "Key": key},
                    ExpiresIn=expires_seconds,
                )
            )

        try:
            return await asyncio.to_thread(_sign)
        except Exception as exc:
            raise StorageError("object storage presign failed") from exc

    async def delete(self, *, key: str, bucket: str | None = None) -> None:
        target = bucket or self._settings.s3_bucket_documents

        def _delete() -> None:
            self._s3().delete_object(Bucket=target, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:
            raise StorageError("object storage delete failed") from exc
