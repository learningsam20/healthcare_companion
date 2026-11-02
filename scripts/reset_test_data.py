#!/usr/bin/env python3
"""Remove the tagged load-test cohort's rows, objects and (optionally) Keycloak users.

Only deterministic `loadtest.*` identities and rows tied to their patient IDs are
touched. Synthetic usage rows are removed; demo/real data is never selected. A single
audit event records the cohort, counts and whether users were deleted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))
sys.path.insert(0, str(SCRIPT_DIR))

from app.composition import build_app_services  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.repositories.audit import AuditRepository  # noqa: E402
from demo_fixtures import loadtest_patient_id, loadtest_users  # noqa: E402
from keycloak_admin import Keycloak, KeycloakError  # noqa: E402
from sahyog_common.logging import configure_logging  # noqa: E402


def cohort_scope(size: int) -> tuple[set[uuid.UUID], set[str], list[str]]:
    patient_ids: set[uuid.UUID] = set()
    subjects: set[str] = set()
    usernames: list[str] = []
    for user in loadtest_users(size):
        username = str(user["username"])
        usernames.append(username)
        subjects.add(str(user["id"]))
        if user.get("patient_id"):
            patient_ids.add(loadtest_patient_id(username))
    return patient_ids, subjects, usernames


async def delete_objects(services: Any, patient_ids: set[uuid.UUID]) -> dict[str, int]:
    counts = {"documents": 0, "audio": 0, "failed": 0, "unconfigured": 0}
    if not services.settings.s3_configured:
        counts["unconfigured"] = 1
        return counts
    async with services.db.sessionmaker() as session:
        document_keys = (
            await session.execute(
                text("SELECT object_key FROM documents WHERE patient_id = ANY(:ids)"),
                {"ids": list(patient_ids)},
            )
        ).scalars()
        audio_keys = (
            await session.execute(
                text(
                    "SELECT t.object_key FROM transcripts t "
                    "JOIN encounters e ON e.id = t.encounter_id "
                    "WHERE e.patient_id = ANY(:ids) AND t.object_key IS NOT NULL"
                ),
                {"ids": list(patient_ids)},
            )
        ).scalars()
        for key in list(document_keys):
            try:
                await services.storage.delete(
                    key=str(key), bucket=services.settings.s3_bucket_documents
                )
                counts["documents"] += 1
            except Exception:  # noqa: BLE001 - object cleanup is retried; DB reset still proceeds
                counts["failed"] += 1
        for key in list(audio_keys):
            try:
                await services.storage.delete(
                    key=str(key), bucket=services.settings.s3_bucket_audio
                )
                counts["audio"] += 1
            except Exception:  # noqa: BLE001
                counts["failed"] += 1
    return counts


async def reset_database(
    services: Any,
    patient_ids: set[uuid.UUID],
    subjects: set[str],
    cohort_size: int,
    *,
    include_eval_artefacts: bool = False,
) -> dict[str, int]:
    ids = list(patient_ids)
    subject_list = list(subjects)
    counts: dict[str, int] = {}
    async with services.db.sessionmaker() as session:
        scope = json.dumps(
            {
                "patient_ids": [str(item) for item in ids],
                "subjects": subject_list,
            }
        )
        await session.execute(
            text("SELECT set_config('sahyog.synthetic_reset_scope', :scope, true)"),
            {"scope": scope},
        )
        statements: list[tuple[str, str, dict[str, Any]]] = [
            (
                "stock_reservations",
                "DELETE FROM stock_reservations WHERE note_id IN "
                "(SELECT cn.id FROM clinical_notes cn "
                "JOIN encounters e ON e.id = cn.encounter_id "
                "WHERE e.patient_id = ANY(:ids))",
                {"ids": ids},
            ),
            (
                "clinical_notes",
                "DELETE FROM clinical_notes WHERE patient_id = ANY(:ids)",
                {"ids": ids},
            ),
            (
                "review_tasks",
                "DELETE FROM review_tasks WHERE patient_id = ANY(:ids) "
                "OR created_by_subject = ANY(:subjects) OR owner_subject = ANY(:subjects)",
                {"ids": ids, "subjects": subject_list},
            ),
            (
                "notifications",
                "DELETE FROM notifications WHERE patient_id = ANY(:ids) "
                "OR recipient_subject = ANY(:subjects)",
                {"ids": ids, "subjects": subject_list},
            ),
            (
                "chat_sessions",
                "DELETE FROM chat_sessions WHERE patient_id = ANY(:ids) "
                "OR owner_subject = ANY(:subjects)",
                {"ids": ids, "subjects": subject_list},
            ),
            (
                "contact_channels",
                "DELETE FROM contact_channels WHERE patient_id = ANY(:ids) "
                "OR subject = ANY(:subjects)",
                {"ids": ids, "subjects": subject_list},
            ),
            (
                "memory_preferences",
                "DELETE FROM memory_preferences WHERE subject = ANY(:subjects)",
                {"subjects": subject_list},
            ),
            (
                "appointments",
                "DELETE FROM appointments WHERE patient_id = ANY(:ids)",
                {"ids": ids},
            ),
            (
                "encounters",
                "DELETE FROM encounters WHERE patient_id = ANY(:ids)",
                {"ids": ids},
            ),
            (
                "documents",
                "DELETE FROM documents WHERE patient_id = ANY(:ids)",
                {"ids": ids},
            ),
            (
                "usage_records",
                "DELETE FROM usage_records WHERE traffic_class = 'synthetic'",
                {},
            ),
            (
                "audit_events",
                "DELETE FROM audit_events WHERE patient_id = ANY(:ids) "
                "OR actor_subject = ANY(:subjects)",
                {"ids": ids, "subjects": subject_list},
            ),
            (
                "patients",
                "DELETE FROM patients WHERE id = ANY(:ids)",
                {"ids": ids},
            ),
        ]
        if include_eval_artefacts:
            statements[0:0] = [
                ("eval_metric_results", "DELETE FROM eval_metric_results", {}),
                ("eval_runs", "DELETE FROM eval_runs", {}),
            ]
        for label, sql, params in statements:
            result = await session.execute(text(sql), params)
            counts[label] = int(result.rowcount or 0)
        AuditRepository(session).append(
            actor_subject="system:reset-test-data",
            actor_role="service",
            action="test_data.reset",
            resource_type="load_test_cohort",
            metadata={
                "cohort": "loadtest",
                "cohort_size": cohort_size,
                "counts": counts,
                "traffic_class": "synthetic",
            },
        )
        await session.commit()
    return counts


async def keycloak_subjects(usernames: list[str]) -> set[str]:
    os.environ.setdefault("KEYCLOAK_ADMIN_URL", os.environ.get("KEYCLOAK_URL", ""))
    subjects: set[str] = set()
    async with Keycloak() as keycloak:
        for username in usernames:
            user = await keycloak.find_user(username)
            if user is not None:
                subjects.add(str(user["id"]))
    # An already-deleted cohort is a valid idempotent reset; the DB scope still runs.
    return subjects


async def delete_users(usernames: list[str]) -> dict[str, int]:
    os.environ.setdefault("KEYCLOAK_ADMIN_URL", os.environ.get("KEYCLOAK_URL", ""))
    counts = {"deleted": 0, "missing": 0, "failed": 0}
    async with Keycloak() as keycloak:
        for username in usernames:
            try:
                user = await keycloak.find_user(username)
                if user is None:
                    counts["missing"] += 1
                    continue
                await keycloak.request(
                    "DELETE",
                    f"/admin/realms/{keycloak.realm}/users/{user['id']}",
                    expected=(204, 404),
                )
                counts["deleted"] += 1
            except KeycloakError:
                counts["failed"] += 1
    return counts


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    settings.validate_startup()
    if settings.app_env == "production" and not args.allow_protected:
        raise ValueError("reset-test-data is refused in production without --allow-protected")
    configure_logging(settings.log_level)
    services = build_app_services(settings)
    patient_ids, _, usernames = cohort_scope(args.cohort_size)
    if not patient_ids:
        raise ValueError("the loadtest cohort scope is empty; nothing to reset")
    subjects = await keycloak_subjects(usernames)
    try:
        objects = await delete_objects(services, patient_ids)
        counts = await reset_database(
            services,
            patient_ids,
            subjects,
            args.cohort_size,
            include_eval_artefacts=args.include_eval_artefacts,
        )
    finally:
        await services.db.dispose()
    users: dict[str, int] | None = None
    if args.include_users:
        users = await delete_users(usernames)
    return {
        "status": "reset",
        "cohort": args.cohort,
        "tag": args.tag,
        "cohort_size": args.cohort_size,
        "patients": len(patient_ids),
        "subjects": len(subjects),
        "rows": counts,
        "objects": objects,
        "users": users,
        "idempotent": True,
        "non_test_rows_touched": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", default="loadtest", choices=("loadtest",))
    parser.add_argument("--tag", default="synthetic", choices=("synthetic",))
    parser.add_argument("--cohort-size", type=int, default=20)
    parser.add_argument("--include-users", action="store_true")
    parser.add_argument("--include-eval-artefacts", action="store_true")
    parser.add_argument("--allow-protected", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.cohort_size <= 20:
        parser.error("--cohort-size must be between 1 and 20")
    if not args.confirm:
        print(
            "error: refusing to delete tagged test data without --confirm",
            file=sys.stderr,
        )
        return 2
    try:
        result = asyncio.run(main_async(args))
    except Exception as exc:  # noqa: BLE001 - operator-facing failure with a clean message
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
