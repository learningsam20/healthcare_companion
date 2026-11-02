from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from asyncpg.exceptions import RaiseError

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT / ".env"


def _dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _setting(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key) or _dotenv().get(key) or default


@pytest.fixture
async def connection() -> AsyncIterator[asyncpg.Connection[Any]]:
    host = _setting("POSTGRES_HOST", "127.0.0.1")
    port = int(_setting("POSTGRES_PORT", "5724") or "5724")
    user = _setting("POSTGRES_USER", "sahyog")
    password = _setting("POSTGRES_PASSWORD")
    database = _setting("POSTGRES_DB", "sahyog")
    if password is None:
        pytest.fail("POSTGRES_PASSWORD is not set; run against a Compose stack with a filled .env")
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            timeout=5,
        )
    except OSError as exc:
        pytest.fail(
            f"Postgres is not reachable at {host}:{port}; start the Compose stack first ({exc})"
        )
    try:
        yield conn
    finally:
        await conn.close()


async def test_postgres_schema_is_migrated_with_pgvector(
    connection: asyncpg.Connection[Any],
) -> None:
    server_version = await connection.fetchval("SHOW server_version")
    assert server_version.startswith("16")

    extensions = {
        row["extname"] for row in await connection.fetch("SELECT extname FROM pg_extension")
    }
    assert {"vector", "pg_trgm", "pgcrypto", "btree_gin"} <= extensions

    tables = {
        row["tablename"]
        for row in await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    }
    assert {
        "patients",
        "appointments",
        "audit_events",
        "documents",
        "usage_records",
        "data_deletion_requests",
    } <= tables

    patient_columns = {
        row["column_name"]
        for row in await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'patients'"
        )
    }
    assert "deleted_at" in patient_columns

    revision = await connection.fetchval("SELECT version_num FROM alembic_version")
    assert revision == "0009_consent_granted_default"

    consent_columns = {
        row["column_name"]
        for row in await connection.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'consents'"
        )
    }
    assert {"grantor_subject", "purpose", "granted_at", "revoked_at"} <= consent_columns

    audit_columns = {
        row["column_name"]
        for row in await connection.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'audit_events'"
        )
    }
    assert "consent_id" in audit_columns


async def test_audit_events_reject_update_and_delete(
    connection: asyncpg.Connection[Any],
) -> None:
    statements = (
        "UPDATE audit_events SET action = 'tampered' WHERE id = $1",
        "DELETE FROM audit_events WHERE id = $1",
    )
    for statement in statements:
        transaction = connection.transaction()
        await transaction.start()
        try:
            event_id = uuid.uuid4()
            await connection.execute(
                """
                INSERT INTO audit_events
                    (id, actor_subject, actor_role, action, resource_type, metadata)
                VALUES ($1, $2, $3, $4, $5, '{}'::jsonb)
                """,
                event_id,
                "integration-test",
                "system",
                "integration.check",
                "audit_events",
            )
            with pytest.raises(RaiseError, match="append-only"):
                await connection.execute(statement, event_id)
        finally:
            await transaction.rollback()
