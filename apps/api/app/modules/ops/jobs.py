"""Scheduled operational jobs: host backup stub and pharmacy stock drop import.

Backup invokes ``scripts/backup.sh`` when ``BACKUP_OUT_DIR`` is set. The Compose
API/scheduler image includes the script but usually lacks Docker socket access, so
an unconfigured or failed run is recorded in ``job_runs`` rather than pretended
successful. Operators can still run the script on the host (see runbook).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from sahyog_common.files import find_repo_root

from app.core.services import Services
from app.modules.analytics.jobs import _job
from app.modules.pharmacy.service import PharmacyService

logger = logging.getLogger(__name__)


class OpsJobUnconfigured(RuntimeError):
    """Raised when a required ops setting is missing so ARQ marks the run failed."""


def backup_script_path() -> Path:
    return find_repo_root() / "scripts" / "backup.sh"


async def run_scheduled_backup(services: Services) -> dict[str, Any]:
    """Run ``scripts/backup.sh --out $BACKUP_OUT_DIR`` or fail visibly when unset."""
    out_dir = (getattr(services.settings, "backup_out_dir", "") or "").strip()
    script = backup_script_path()
    async with _job(services, "ops.backup") as (_session, run):
        if not out_dir:
            detail = {
                "configured": False,
                "error_code": "backup_unconfigured",
                "hint": "Set BACKUP_OUT_DIR to a host path outside the repo, or run scripts/backup.sh manually.",
            }
            run.detail = detail
            raise OpsJobUnconfigured("backup_unconfigured: BACKUP_OUT_DIR is not set")
        if not script.is_file():
            detail = {
                "configured": True,
                "error_code": "backup_script_missing",
                "script": str(script),
            }
            run.detail = detail
            raise OpsJobUnconfigured(f"backup_script_missing: {script}")

        env = {**os.environ, "BACKUP_OUT_DIR": out_dir}
        proc = await asyncio.create_subprocess_exec(
            "bash",
            str(script),
            "--out",
            out_dir,
            "--note",
            "arq-ops.backup",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(script.parent.parent),
        )
        stdout_b, stderr_b = await proc.communicate()
        detail = {
            "configured": True,
            "out_dir": out_dir,
            "returncode": proc.returncode,
            "stdout_tail": (stdout_b or b"")[-2000:].decode("utf-8", errors="replace"),
            "stderr_tail": (stderr_b or b"")[-2000:].decode("utf-8", errors="replace"),
        }
        run.detail = detail
        if proc.returncode != 0:
            raise RuntimeError(f"backup_failed: exit={proc.returncode}")
        logger.info(
            "scheduled backup completed",
            extra={"event": "ops.backup", "extra_fields": {"out_dir": out_dir}},
        )
        return detail


async def run_stock_drop_import(services: Services) -> dict[str, Any]:
    """Import CSVs from stock drop_dir into stock_items; record job_runs."""
    async with _job(services, "ops.stock_import") as (session, run):
        cfg = getattr(services, "stock_config", None) or {}
        drop = str(cfg.get("drop_dir") or "").strip()
        if not drop:
            detail = {
                "configured": False,
                "error_code": "stock_drop_unconfigured",
                "hint": "Set drop_dir in config/stock.yaml or import via POST /api/v1/pharmacy/stock/import.",
            }
            run.detail = detail
            raise OpsJobUnconfigured("stock_drop_unconfigured: drop_dir missing")
        payload = await PharmacyService(services, session).import_drop_directory()
        detail = {"configured": True, **payload}
        run.detail = detail
        logger.info(
            "pharmacy stock drop import",
            extra={"event": "pharmacy.stock_drop_import", "extra_fields": payload},
        )
        return detail
