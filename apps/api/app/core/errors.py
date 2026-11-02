from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sahyog_common.errors import ProblemError
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    problem = ProblemError(status=status, code=code, title=title, detail=detail).to_problem(
        instance=request.url.path
    )
    return JSONResponse(
        status_code=status,
        content=problem,
        media_type="application/problem+json",
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=exc.to_problem(instance=request.url.path),
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem_response(
            request,
            status=422,
            code="request_invalid",
            title="Request validation failed",
            detail="One or more request fields are invalid.",
        )

    @app.exception_handler(SQLAlchemyError)
    async def _database(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database error", exc_info=exc, extra={"event": "database.error"})
        return _problem_response(
            request,
            status=503,
            code="database_unavailable",
            title="Database unavailable",
            detail="The request could not be completed. Try again shortly.",
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error", exc_info=exc, extra={"event": "request.unhandled"})
        return _problem_response(
            request,
            status=500,
            code="internal_error",
            title="Internal error",
            detail="The request could not be completed.",
        )
