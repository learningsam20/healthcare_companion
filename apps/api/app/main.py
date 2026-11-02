from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sahyog_common.feature_flags import FeatureFlagError
from sahyog_common.logging import configure_logging

from app.composition import build_app_services
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import SecurityHeadersMiddleware, TraceMiddleware
from app.core.telemetry import configure_telemetry
from app.modules.abdm.router import router as abdm_router
from app.modules.admin.observability import router as admin_observability_router
from app.modules.admin.router import router as admin_router
from app.modules.analytics.router import router as analytics_router
from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.compliance.guard import DpdpStopProcessingMiddleware
from app.modules.consents.router import router as consents_router
from app.modules.fhir.router import router as fhir_router
from app.modules.handoffs.router import router as handoffs_router
from app.modules.health.router import router as health_router
from app.modules.incidents.router import router as incidents_router
from app.modules.memory.router import router as memory_router
from app.modules.meta.router import router as meta_router
from app.modules.notifications.router import me_router
from app.modules.notifications.router import router as notifications_router
from app.modules.nursing.router import router as nursing_router
from app.modules.patients.router import router as patients_router
from app.modules.pharmacy.router import router as pharmacy_router
from app.modules.privacy.router import router as privacy_router
from app.modules.records.internal import router as records_internal_router
from app.modules.records.router import router as records_router
from app.modules.review.router import router as review_router
from app.modules.scheduling.internal import router as scheduling_internal_router
from app.modules.scheduling.router import router as scheduling_router
from app.modules.scheduling.waitlist_router import router as waitlist_router
from app.modules.scribe.internal import router as scribe_internal_router
from app.modules.scribe.router import router as scribe_router
from app.repositories.flags import FeatureFlagRepository

logger = logging.getLogger(__name__)


async def _apply_runtime_overrides(app: FastAPI) -> None:
    services = app.state.services
    if not services.settings.database_url:
        return
    try:
        async with services.db.sessionmaker() as session:
            overrides = await FeatureFlagRepository(session).overrides()
    except Exception as exc:
        logger.warning(
            "feature overrides not loaded",
            exc_info=exc,
            extra={"event": "features.overrides_unavailable"},
        )
        return
    for key, value in overrides.items():
        try:
            services.features.set_runtime(key, value)
        except FeatureFlagError as exc:
            logger.warning(
                "feature override ignored",
                extra={"event": "features.override_ignored", "extra_fields": {"key": key}},
            )
            logger.debug("override rejected: %s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    resolved.validate_startup()
    configure_logging(resolved.log_level)
    configure_telemetry(resolved)
    if "*" in resolved.cors_origin_list and resolved.app_env != "dev":
        raise ValueError("CORS_ORIGINS must be an exact allowlist outside dev")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        from app.agents.checkpointer import close_checkpointer, open_checkpointer

        services = build_app_services(resolved)
        services.checkpointer = await open_checkpointer(resolved.database_url)
        if resolved.ha_mode or resolved.checkpointer_required:
            if services.checkpointer is None:
                raise RuntimeError(
                    "HA_MODE/CHECKPOINTER_REQUIRED is set but the Postgres checkpointer "
                    "failed to open; refusing to start"
                )
        if resolved.external_egress_enabled:
            # No external route without a healthy composite PII model.
            from app.agents.pii_gate import PiiGate

            pii_health = await PiiGate(resolved).health()
            if not pii_health.get("composite_ready"):
                raise RuntimeError(
                    "EXTERNAL_EGRESS_ENABLED requires a healthy composite PII engine "
                    f"(got {pii_health!r}); download models and keep PII_ENGINE=composite"
                )
        app.state.services = services
        await _apply_runtime_overrides(app)
        logger.info(
            "api started",
            extra={
                "event": "app.started",
                "extra_fields": {
                    "profile": resolved.app_profile,
                    "environment": resolved.app_env,
                    "version": resolved.version,
                    "checkpointer": bool(services.checkpointer),
                    "external_egress": resolved.external_egress_enabled,
                },
            },
        )
        try:
            yield
        finally:
            await close_checkpointer(services.checkpointer)
            await services.db.dispose()

    docs_enabled = resolved.app_env != "production"
    app = FastAPI(
        title="Sahyog Care Companion API",
        version=resolved.version,
        description=(
            "Role-scoped healthcare assistant API. Identified content never leaves the "
            "local boundary; every model call is resolved by purpose through LiteLLM."
        ),
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = resolved
    app.add_middleware(SecurityHeadersMiddleware, hsts=resolved.app_env == "production")
    app.add_middleware(DpdpStopProcessingMiddleware)
    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Trace-Id",
            "X-Request-Id",
            "X-Consent-Id",
        ],
        expose_headers=["X-Trace-Id"],
        max_age=600,
    )
    register_exception_handlers(app)
    for router in (
        health_router,
        meta_router,
        auth_router,
        consents_router,
        chat_router,
        scheduling_router,
        scheduling_internal_router,
        waitlist_router,
        patients_router,
        fhir_router,
        abdm_router,
        pharmacy_router,
        privacy_router,
        records_router,
        records_internal_router,
        memory_router,
        nursing_router,
        scribe_router,
        scribe_internal_router,
        review_router,
        handoffs_router,
        incidents_router,
        notifications_router,
        me_router,
        analytics_router,
        admin_router,
        admin_observability_router,
    ):
        app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {
            "name": resolved.app_name,
            "version": resolved.version,
            "docs": "/docs" if docs_enabled else None,
            "health": "/healthz",
        }

    return app


app = create_app()
