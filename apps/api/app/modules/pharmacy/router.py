from __future__ import annotations

import secrets
import uuid
from typing import Annotated, Any

from app.core.config import get_settings
from app.core.db import get_session
from app.core.pagination import GridResponse
from app.core.security import AuthContext, Role, get_auth_context
from app.core.services import Services, get_services
from app.modules.pharmacy.schemas import StockItemOut, StockItemWrite
from app.modules.pharmacy.service import PharmacyService
from fastapi import APIRouter, Depends, File, Header, Query, Request, UploadFile
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/pharmacy", tags=["pharmacy"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _service(services: Services, session: AsyncSession) -> PharmacyService:
    return PharmacyService(services, session)


def _stock_api_key_ok(provided: str | None) -> bool:
    expected = get_settings().stock_api_key.strip()
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided.strip(), expected)


@router.get("/stock")
async def list_stock(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    clinic_code: Annotated[str | None, Query(max_length=40)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> GridResponse[StockItemOut]:
    items, meta = await _service(services, session).list_items(
        context, query=q, clinic_code=clinic_code, page=page, page_size=page_size
    )
    await session.commit()
    return GridResponse(items=items, meta=meta)


@router.get("/stock/lookup")
async def lookup_stock(
    services: ServicesDep,
    session: SessionDep,
    drug_name: Annotated[str, Query(min_length=1, max_length=200)],
    clinic_code: Annotated[str, Query(min_length=1, max_length=40)],
    x_stock_api_key: Annotated[str | None, Header(alias="X-Stock-Api-Key")] = None,
) -> dict[str, Any]:
    """DB-backed stock lookup for MCP / batch callers (X-Stock-Api-Key)."""
    if not _stock_api_key_ok(x_stock_api_key):
        raise ProblemError(
            401,
            "unauthorized",
            "Stock lookup rejected",
            "A valid X-Stock-Api-Key is required.",
        )
    return await _service(services, session).lookup_guard(
        drug_name=drug_name, clinic_code=clinic_code
    )


@router.get("/stock/status")
async def staff_stock_status(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    drug_name: Annotated[str, Query(min_length=1, max_length=200)],
    clinic_code: Annotated[str, Query(min_length=1, max_length=40)],
) -> dict[str, Any]:
    if context.primary_role not in {
        Role.PHARMACIST,
        Role.DOCTOR,
        Role.FRONT_DESK,
        Role.ADMIN,
    }:
        raise ProblemError(403, "forbidden", "Stock lookup rejected", "Your role cannot read stock.")
    return await _service(services, session).lookup_guard(
        drug_name=drug_name, clinic_code=clinic_code
    )


@router.get("/stock/typeahead")
async def stock_typeahead(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=120)],
    clinic_code: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
) -> dict[str, object]:
    items, total = await _service(services, session).typeahead(
        context, query=q, clinic_code=clinic_code, limit=limit
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "q": q,
    }


@router.get("/stock/{item_id}", response_model=StockItemOut)
async def get_stock(
    item_id: uuid.UUID,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> StockItemOut:
    return await _service(services, session).get(context, item_id)


@router.post("/stock", status_code=201)
async def create_stock(
    body: StockItemWrite,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> StockItemOut:
    item = await _service(services, session).create(context, body, _trace(request))
    await session.commit()
    return item


@router.patch("/stock/{item_id}")
async def update_stock(
    item_id: uuid.UUID,
    body: StockItemWrite,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> StockItemOut:
    item = await _service(services, session).update(context, item_id, body, _trace(request))
    await session.commit()
    return item


@router.delete("/stock/{item_id}", status_code=204)
async def delete_stock(
    item_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> None:
    await _service(services, session).delete(context, item_id, _trace(request))
    await session.commit()


@router.post("/stock/import")
async def import_stock(
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    file: UploadFile = File(...),
):
    raw = await file.read()
    result = await _service(services, session).import_csv(
        context,
        raw=raw,
        source=file.filename or "upload.csv",
        trace_id=_trace(request),
    )
    await session.commit()
    return result
