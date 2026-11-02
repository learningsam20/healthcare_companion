#!/usr/bin/env python3
"""Aggregate-only data-quality checks for the sample and load-test datasets.

Never selects patient names, text, tokens or embeddings. Exits non-zero on referential
or integrity failures; reports advisory counts without failing on empty optional data.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py-common"))

from app.core.config import get_settings  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

REQUIRED_TABLES = [
    "patients",
    "consents",
    "chat_sessions",
    "chat_messages",
    "appointments",
    "documents",
    "document_chunks",
    "notifications",
    "notification_deliveries",
    "encounters",
    "transcripts",
    "clinical_notes",
    "audit_events",
    "usage_records",
]

ORPHAN_CHECKS = [
    (
        "appointments.patient_id",
        "SELECT count(*) FROM appointments a LEFT JOIN patients p ON p.id = a.patient_id "
        "WHERE a.patient_id IS NOT NULL AND p.id IS NULL",
    ),
    (
        "consents.patient_id",
        "SELECT count(*) FROM consents c LEFT JOIN patients p ON p.id = c.patient_id "
        "WHERE p.id IS NULL",
    ),
    (
        "chat_sessions.patient_id",
        "SELECT count(*) FROM chat_sessions s LEFT JOIN patients p ON p.id = s.patient_id "
        "WHERE s.patient_id IS NOT NULL AND p.id IS NULL",
    ),
    (
        "chat_messages.session_id",
        "SELECT count(*) FROM chat_messages m LEFT JOIN chat_sessions s ON s.id = m.session_id "
        "WHERE s.id IS NULL",
    ),
    (
        "documents.patient_id",
        "SELECT count(*) FROM documents d LEFT JOIN patients p ON p.id = d.patient_id "
        "WHERE p.id IS NULL",
    ),
    (
        "document_chunks.document_id",
        "SELECT count(*) FROM document_chunks c LEFT JOIN documents d ON d.id = c.document_id "
        "WHERE d.id IS NULL",
    ),
]


async def _count(connection: Any, sql: str) -> int:
    value = await connection.scalar(text(sql))
    return int(value or 0)


async def main() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    failures: list[dict[str, str]] = []
    advisory: list[dict[str, Any]] = []
    tables: dict[str, int] = {}
    try:
        async with engine.connect() as connection:
            present = {
                row[0]
                for row in (
                    await connection.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
                    )
                ).all()
            }
            missing = [name for name in REQUIRED_TABLES if name not in present]
            if missing:
                failures.append({"check": "required_tables", "detail": ", ".join(missing)})
            for name in REQUIRED_TABLES:
                if name in present:
                    # name comes from the fixed REQUIRED_TABLES allowlist, never from input.
                    tables[name] = await _count(
                        connection,
                        f'SELECT count(*) FROM "{name}"',  # noqa: S608
                    )

            for label, sql in ORPHAN_CHECKS:
                if label.split(".")[0] not in present:
                    continue
                orphans = await _count(connection, sql)
                if orphans:
                    failures.append({"check": f"orphan:{label}", "detail": str(orphans)})

            if "documents" in present:
                duplicates = await _count(
                    connection,
                    "SELECT count(*) FROM ("
                    "SELECT patient_id, checksum_sha256 FROM documents "
                    "GROUP BY patient_id, checksum_sha256 HAVING count(*) > 1"
                    ") duplicates",
                )
                if duplicates:
                    failures.append({"check": "duplicate_documents", "detail": str(duplicates)})

            dims: int | None = None
            if "document_chunks" in present and tables.get("document_chunks", 0):
                dims = await connection.scalar(
                    text("SELECT vector_dims(embedding) FROM document_chunks LIMIT 1")
                )
                if dims != settings.embedding_dim:
                    failures.append(
                        {
                            "check": "embedding_dimension",
                            "detail": f"{dims} != {settings.embedding_dim}",
                        }
                    )

            traffic: dict[str, int] = {}
            if "chat_sessions" in present:
                for row in (
                    await connection.execute(
                        text(
                            "SELECT traffic_class, count(*) FROM chat_sessions "
                            "GROUP BY traffic_class ORDER BY traffic_class"
                        )
                    )
                ).all():
                    traffic[str(row[0])] = int(row[1])

            if "clinical_notes" in present:
                unsigned = await _count(
                    connection,
                    "SELECT count(*) FROM clinical_notes WHERE status = 'signed' "
                    "AND signed_at IS NULL",
                )
                if unsigned:
                    failures.append({"check": "signed_without_timestamp", "detail": str(unsigned)})

            if "consents" in present:
                expired_active = await _count(
                    connection,
                    "SELECT count(*) FROM consents WHERE status = 'active' "
                    "AND expires_at IS NOT NULL AND expires_at <= now()",
                )
                if expired_active:
                    advisory.append(
                        {
                            "check": "active_consents_past_expiry",
                            "value": expired_active,
                            "note": "the scheduler expires these; run retention.sh to verify",
                        }
                    )

            migration = None
            if "alembic_version" in present or await connection.scalar(
                text("SELECT to_regclass('public.alembic_version')")
            ):
                migration = await connection.scalar(text("SELECT version_num FROM alembic_version"))

        report = {
            "status": "failed" if failures else "passed",
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "profile": settings.app_profile,
            "embedding_dim": settings.embedding_dim,
            "migration": migration,
            "tables": tables,
            "chat_traffic_class": traffic,
            "advisory": advisory,
            "failures": failures,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if failures else 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(__import__("asyncio").run(main()))
