from __future__ import annotations

import csv
import datetime as dt
import io
import math
import uuid
from typing import Any

from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role
from app.core.services import Services
from app.modules.pharmacy.schemas import StockImportOut, StockItemOut, StockItemWrite
from app.repositories.audit import AuditRepository
from app.repositories.models import StockItemRecord
from app.repositories.stock import StockRepository
from sahyog_common.errors import ProblemError
from sahyog_common.stock import LOW_STOCK_THRESHOLD, StockItem
from sqlalchemy.ext.asyncio import AsyncSession


def _problem(status: int, code: str, detail: str) -> ProblemError:
    return ProblemError(status, code, "Pharmacy request rejected", detail)


def _status_fields(
    row: StockItemRecord, *, now: dt.datetime, stale_after_minutes: int
) -> dict[str, Any]:
    item = StockItem(
        sku=row.sku,
        drug_name=row.drug_name,
        form=row.form,
        strength=row.strength,
        quantity=row.quantity,
        clinic_code=row.clinic_code,
        updated_at=row.updated_at,
        source=row.source,
    )
    data = item.as_dict(now=now, stale_after_minutes=stale_after_minutes)
    return {
        "status": data["status"],
        "stale": data["stale"],
        "age_minutes": data["age_minutes"],
    }


class PharmacyService:
    def __init__(self, services: Services, session: AsyncSession) -> None:
        self._services = services
        self._session = session
        self._repo = StockRepository(session)
        self._audit = AuditRepository(session)

    @property
    def _stale_after(self) -> int:
        return int(self._services.stock_config.get("stale_after_minutes", 60))

    def _require_staff(self, context: AuthContext) -> None:
        if context.primary_role not in {
            Role.PHARMACIST,
            Role.DOCTOR,
            Role.FRONT_DESK,
            Role.ADMIN,
        }:
            raise _problem(403, "forbidden", "Your role cannot manage pharmacy stock.")

    def _require_writer(self, context: AuthContext) -> None:
        if context.primary_role not in {Role.PHARMACIST, Role.ADMIN}:
            raise _problem(403, "forbidden", "Only a pharmacist or admin can edit stock.")

    def _to_out(self, row: StockItemRecord, *, now: dt.datetime) -> StockItemOut:
        extra = _status_fields(row, now=now, stale_after_minutes=self._stale_after)
        return StockItemOut(
            id=row.id,
            sku=row.sku,
            drug_name=row.drug_name,
            form=row.form,
            strength=row.strength,
            quantity=row.quantity,
            clinic_code=row.clinic_code,
            updated_at=row.updated_at,
            source=row.source,
            **extra,
        )

    async def list_items(
        self,
        context: AuthContext,
        *,
        query: str | None,
        clinic_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StockItemOut], GridMeta]:
        self._require_staff(context)
        offset = (page - 1) * page_size
        rows, total = await self._repo.list(
            query=query, clinic_code=clinic_code, limit=page_size, offset=offset
        )
        now = dt.datetime.now(dt.UTC)
        items = [self._to_out(row, now=now) for row in rows]
        meta = GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="drug_name",
            order="asc",
            pages=math.ceil(total / page_size) if total else 0,
        )
        return items, meta

    async def typeahead(
        self, context: AuthContext, *, query: str, clinic_code: str | None, limit: int
    ) -> tuple[list[StockItemOut], int]:
        self._require_staff(context)
        rows, total = await self._repo.list(
            query=query, clinic_code=clinic_code, limit=limit, offset=0
        )
        now = dt.datetime.now(dt.UTC)
        return [self._to_out(row, now=now) for row in rows], int(total)

    async def get(self, context: AuthContext, item_id: uuid.UUID) -> StockItemOut:
        self._require_staff(context)
        row = await self._repo.get(item_id)
        if row is None:
            raise _problem(404, "not_found", "Stock item was not found.")
        return self._to_out(row, now=dt.datetime.now(dt.UTC))

    async def create(
        self, context: AuthContext, body: StockItemWrite, trace_id: str | None
    ) -> StockItemOut:
        self._require_writer(context)
        now = dt.datetime.now(dt.UTC)
        saved = await self._repo.upsert(
            StockItemRecord(
                sku=body.sku.strip(),
                drug_name=body.drug_name.strip(),
                form=body.form.strip(),
                strength=body.strength.strip(),
                quantity=body.quantity,
                clinic_code=body.clinic_code.strip().upper(),
                updated_at=now,
                source=body.source.strip() or "manual",
            )
        )
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="pharmacy.stock_upserted",
            resource_type="stock_item",
            resource_id=str(saved.id),
            trace_id=trace_id,
            metadata={"sku": saved.sku, "clinic_code": saved.clinic_code},
        )
        return self._to_out(saved, now=now)

    async def update(
        self,
        context: AuthContext,
        item_id: uuid.UUID,
        body: StockItemWrite,
        trace_id: str | None,
    ) -> StockItemOut:
        self._require_writer(context)
        row = await self._repo.get(item_id)
        if row is None:
            raise _problem(404, "not_found", "Stock item was not found.")
        now = dt.datetime.now(dt.UTC)
        row.sku = body.sku.strip()
        row.drug_name = body.drug_name.strip()
        row.form = body.form.strip()
        row.strength = body.strength.strip()
        row.quantity = body.quantity
        row.clinic_code = body.clinic_code.strip().upper()
        row.updated_at = now
        row.source = body.source.strip() or row.source
        await self._session.flush()
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="pharmacy.stock_updated",
            resource_type="stock_item",
            resource_id=str(row.id),
            trace_id=trace_id,
            metadata={"sku": row.sku, "clinic_code": row.clinic_code},
        )
        return self._to_out(row, now=now)

    async def delete(
        self, context: AuthContext, item_id: uuid.UUID, trace_id: str | None
    ) -> None:
        self._require_writer(context)
        deleted = await self._repo.delete(item_id)
        if not deleted:
            raise _problem(404, "not_found", "Stock item was not found.")
        self._audit.append(
            actor_subject=context.subject,
            actor_role=context.primary_role.value,
            action="pharmacy.stock_deleted",
            resource_type="stock_item",
            resource_id=str(item_id),
            trace_id=trace_id,
            metadata={},
        )

    async def import_csv(
        self,
        context: AuthContext | None,
        *,
        raw: bytes,
        source: str,
        trace_id: str | None = None,
        actor_subject: str = "system:stock-import",
        actor_role: str = "service",
    ) -> StockImportOut:
        if context is not None:
            self._require_writer(context)
            actor_subject = context.subject
            actor_role = context.primary_role.value
        now = dt.datetime.now(dt.UTC)
        errors: list[Any] = []
        try:
            text = raw.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            record = await self._repo.record_import(
                source=source,
                raw=raw,
                as_of=now,
                row_count=0,
                status="failed",
                errors=[{"error": str(exc)}],
            )
            return StockImportOut.model_validate(record)

        count = 0
        for index, row in enumerate(rows, start=2):
            try:
                updated_at = dt.datetime.fromisoformat(
                    str(row["updated_at"]).replace("Z", "+00:00")
                )
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=dt.UTC)
                await self._repo.upsert(
                    StockItemRecord(
                        sku=str(row["sku"]).strip(),
                        drug_name=str(row["drug_name"]).strip(),
                        form=str(row.get("form", "")).strip(),
                        strength=str(row.get("strength", "")).strip(),
                        quantity=int(row.get("quantity", 0)),
                        clinic_code=str(row["clinic_code"]).strip().upper(),
                        updated_at=updated_at,
                        source=source,
                    )
                )
                count += 1
            except (KeyError, TypeError, ValueError) as exc:
                errors.append({"line": index, "error": str(exc)})
        status = "succeeded" if not errors else ("partial" if count else "failed")
        record = await self._repo.record_import(
            source=source,
            raw=raw,
            as_of=now,
            row_count=count,
            status=status,
            errors=errors,
        )
        self._audit.append(
            actor_subject=actor_subject,
            actor_role=actor_role,
            action="pharmacy.stock_imported",
            resource_type="stock_import",
            resource_id=str(record.id),
            trace_id=trace_id,
            metadata={"row_count": count, "status": status, "errors": len(errors)},
        )
        return StockImportOut.model_validate(record)

    async def import_configured_csv(self) -> StockImportOut:
        raw_path = str(self._services.stock_config.get("csv_path", "config/stock.csv"))
        root = self._services.settings.config_dir.parent
        from pathlib import Path

        path = Path(raw_path)
        path = path if path.is_absolute() else root / path
        raw = path.read_bytes()
        source = str(self._services.stock_config.get("source_label", "demo-stock"))
        return await self.import_csv(
            None, raw=raw, source=source, actor_subject="system:stock-import"
        )

    def _paths(self) -> dict[str, Any]:
        root = self._services.settings.config_dir.parent
        cfg = self._services.stock_config

        def resolve(key: str, default: str) -> Any:
            from pathlib import Path

            raw = str(cfg.get(key, default))
            path = Path(raw)
            return path if path.is_absolute() else root / path

        return {
            "csv": resolve("csv_path", "config/stock.csv"),
            "incoming": resolve("drop_dir", "data/stock/incoming"),
            "processed": resolve("drop_processed_dir", "data/stock/processed"),
            "failed": resolve("drop_failed_dir", "data/stock/failed"),
        }

    async def lookup_guard(
        self, *, drug_name: str, clinic_code: str
    ) -> dict[str, Any]:
        """Return stock status from stock_items (API/DB source of truth)."""
        row = await self._repo.find(drug_name=drug_name, clinic_code=clinic_code)
        now = dt.datetime.now(dt.UTC)
        if row is None:
            return {
                "available": False,
                "status": "unknown",
                "reason": "not_in_inventory",
                "drug_name": drug_name,
                "clinic_code": clinic_code,
                "source": str(self._services.stock_config.get("source_label", "stock")),
                "as_of": None,
                "stale": True,
            }
        extra = _status_fields(row, now=now, stale_after_minutes=self._stale_after)
        available = extra["status"] == "in_stock" or (
            extra["status"] == "low" and row.quantity > 0
        )
        return {
            "available": available and not extra["stale"],
            "sku": row.sku,
            "drug_name": row.drug_name,
            "quantity": row.quantity,
            "clinic_code": row.clinic_code,
            "source": row.source,
            "as_of": row.updated_at.isoformat(),
            **extra,
            "low_stock_threshold": LOW_STOCK_THRESHOLD,
        }

    async def import_drop_directory(self) -> dict[str, Any]:
        """Import every *.csv from drop_dir, then move to processed/ or failed/."""
        from pathlib import Path

        paths = self._paths()
        incoming: Path = paths["incoming"]
        processed: Path = paths["processed"]
        failed: Path = paths["failed"]
        for directory in (incoming, processed, failed):
            directory.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        for path in sorted(incoming.glob("*.csv")):
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
            raw = path.read_bytes()
            try:
                imported = await self.import_csv(
                    None,
                    raw=raw,
                    source=path.name,
                    actor_subject="system:stock-drop",
                )
                dest = processed / f"{stamp}_{path.name}"
                path.replace(dest)
                results.append(
                    {
                        "file": path.name,
                        "status": imported.status,
                        "row_count": imported.row_count,
                        "dest": str(dest),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - batch continues on bad files
                dest = failed / f"{stamp}_{path.name}"
                try:
                    path.replace(dest)
                except OSError:
                    pass
                results.append({"file": path.name, "status": "failed", "error": str(exc)})
        return {"processed": len(results), "files": results}
