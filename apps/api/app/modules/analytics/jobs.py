"""Scheduled analytics jobs: snapshots, advisory insights, audit anchors, staleness."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.agents.llm_gateway import LlmGateway, LlmGatewayError
from app.core.services import Services
from app.core.storage import StorageError
from app.modules.analytics.reconciliation import reconcile_spend
from app.modules.notifications.service import NotificationService
from app.repositories.analytics import AnalyticsRepository
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    AnalyticsSnapshot,
    AuditEvent,
    EvalRun,
    Insight,
    JobRun,
    SpendReconciliation,
)
from app.repositories.usage import UsageRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

INSIGHT_WINDOW_DAYS = 30
INSIGHT_EXPIRY_DAYS = 14
SNAPSHOT_STALE_HOURS = 26
RECONCILIATION_STALE_HOURS = 26


@asynccontextmanager
async def _job(services: Services, name: str) -> AsyncIterator[tuple[AsyncSession, JobRun]]:
    async with services.db.sessionmaker() as session:
        run = JobRun(job_name=name, status="running")
        session.add(run)
        await session.flush()
        try:
            yield session, run
        except Exception as exc:
            run.status = "failed"
            run.error_code = type(exc).__name__[:80]
            run.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()
            raise
        else:
            run.status = "succeeded"
            run.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()


async def capture_snapshot(services: Services) -> dict[str, Any]:
    async with _job(services, "analytics.snapshot") as (session, run):
        end = dt.datetime.now(dt.UTC)
        start = end - dt.timedelta(days=1)
        repo = AnalyticsRepository(session)
        counts = await repo.overview_counts(start=start, end=end)
        actions = await repo.audit_action_counts(start=start, end=end)
        consents = await repo.consent_counts()
        usage = await UsageRepository(session).summary(start=start, end=end)
        latest_audit = await repo.latest_audit_at()
        minimum = int(services.app_config.get("analytics", {}).get("small_cell_minimum", 5))
        metrics = {
            "active_users_1d": counts["active_users"],
            "chat_sessions_1d": counts["chat_sessions"],
            "chat_messages_1d": counts["chat_messages"],
            "bookings_confirmed_1d": counts["bookings_confirmed"],
            "red_flag_triggers_1d": actions.get("safety.red_flag_triggered", 0),
            "consent_active": consents.get("active", 0),
            "consent_expired": consents.get("expired", 0),
            "usage_calls_1d": usage["calls"],
            "usage_cost_usd_1d": usage["cost_usd"],
            "latest_audit_at": latest_audit.isoformat() if latest_audit else None,
        }
        suppression_applied = any(
            0 < int(value) < minimum
            for key, value in metrics.items()
            if key.endswith(("_1d", "_active", "_expired")) and isinstance(value, int)
        )
        snapshot = AnalyticsSnapshot(
            period_start=start,
            period_end=end,
            metric_version=str(services.metrics.get("version", "unknown")),
            metrics=metrics,
            suppression_applied=suppression_applied,
        )
        session.add(snapshot)
        await session.flush()
        AuditRepository(session).append(
            actor_subject="system:analytics",
            actor_role="service",
            action="analytics.snapshot_captured",
            resource_type="analytics_snapshot",
            resource_id=str(snapshot.id),
            metadata={
                "metric_version": snapshot.metric_version,
                "suppression_applied": suppression_applied,
                "period_hours": 24,
            },
        )
        run.detail = {
            "snapshot_id": str(snapshot.id),
            "metric_version": snapshot.metric_version,
            "metrics": metrics,
        }
        return {"snapshot_id": str(snapshot.id), "metrics": metrics}


def _deterministic_candidates(
    services: Services,
    *,
    counts: dict[str, int],
    actions: dict[str, int],
    consents: dict[str, int],
    usage: dict[str, Any],
    latest_eval: EvalRun | None,
    latest_reconciliation: SpendReconciliation | None,
    window_end: dt.datetime,
) -> list[dict[str, Any]]:
    day = window_end.strftime("%Y-%m-%d")
    items: list[dict[str, Any]] = []
    if counts["chat_sessions"] == 0:
        items.append(
            {
                "key": "no-observed-usage",
                "area": "adoption",
                "title": "Establish an observed usage baseline",
                "recommendation": (
                    "Run a guided user session and a synthetic load profile before tuning "
                    "capacity or budgets."
                ),
                "impact": "Evidence before optimisation",
                "confidence": "high",
                "effort": "low",
                "owner": "operations",
                "evidence": ["chat_sessions_created = 0 in the selected window"],
            }
        )
    if usage["calls"] == 0:
        items.append(
            {
                "key": "cost-baseline-missing",
                "area": "finops",
                "title": "No application cost baseline",
                "recommendation": (
                    "No app usage cost has been recorded. Establish a baseline before "
                    "setting hard budgets."
                ),
                "impact": "Prevents false precision",
                "confidence": "high",
                "effort": "low",
                "owner": "finance",
                "evidence": ["usage_records calls = 0 in the selected window"],
            }
        )
    if consents.get("expired", 0) > 0:
        items.append(
            {
                "key": "consent-expiry-review",
                "area": "compliance",
                "title": "Review expired caregiver consents",
                "recommendation": (
                    "Confirm access has stopped for every expired caregiver consent."
                ),
                "impact": "Reduces consent-scope risk",
                "confidence": "high",
                "effort": "medium",
                "owner": "compliance",
                "evidence": [f"consent_expired = {consents.get('expired', 0)}"],
            }
        )
    if actions.get("safety.red_flag_triggered", 0) > 0:
        items.append(
            {
                "key": "red-flag-review",
                "area": "quality",
                "title": "Review red-flag handling evidence",
                "recommendation": (
                    "Sample red-flag triggers and confirm each shows the emergency guidance "
                    "and human follow-up."
                ),
                "impact": "Safety evidence, not a score",
                "confidence": "medium",
                "effort": "low",
                "owner": "clinical-safety",
                "evidence": [f"red_flag_triggers = {actions.get('safety.red_flag_triggered', 0)}"],
            }
        )
    if latest_eval is None:
        items.append(
            {
                "key": "evaluation-baseline-missing",
                "area": "quality",
                "title": "Record an evaluation baseline",
                "recommendation": (
                    "Run the RAGAS and DeepEval suites and record dataset hashes, judge alias "
                    "and prompt versions before release review."
                ),
                "impact": "Release evidence",
                "confidence": "high",
                "effort": "medium",
                "owner": "quality",
                "evidence": ["No evaluation run has been recorded."],
            }
        )
    elif latest_eval.status != "passed":
        items.append(
            {
                "key": "evaluation-failing",
                "area": "quality",
                "title": "A recent evaluation run did not pass",
                "recommendation": (
                    "Inspect the failing cases before promoting a model, prompt or route change."
                ),
                "impact": "Prevents a silent quality regression",
                "confidence": "high",
                "effort": "medium",
                "owner": "quality",
                "evidence": [
                    f"eval_run {latest_eval.id} status = {latest_eval.status}",
                    f"failed_cases = {latest_eval.failed_cases}",
                ],
            }
        )
    if latest_reconciliation is not None and latest_reconciliation.status == "variance":
        items.append(
            {
                "key": "finops-reconciliation-variance",
                "area": "finops",
                "title": "Gateway spend does not match application usage",
                "recommendation": (
                    "Review unmatched gateway calls and retries. Do not edit usage rows to "
                    "force a match; correct the accounting path instead."
                ),
                "impact": "Prevents billing-grade drift",
                "confidence": "high",
                "effort": "medium",
                "owner": "finance",
                "evidence": [
                    f"variance_pct = {latest_reconciliation.variance_pct}",
                    f"unmatched_gateway_calls = {latest_reconciliation.unmatched_gateway_calls}",
                    f"unmatched_app_calls = {latest_reconciliation.unmatched_app_calls}",
                ],
            }
        )
    profile = services.finops_model.get("profiles", {}).get(
        services.finops_model.get("what_if_defaults", {}).get("profile", "P"), {}
    )
    items.append(
        {
            "key": "local-routing",
            "area": "finops",
            "title": "Keep record-bearing prompts local",
            "recommendation": (
                "Keep record-bearing prompts on local aliases; reserve external aliases for "
                "de-identified text."
            ),
            "impact": (
                "External share target: "
                f"{profile.get('inputs', {}).get('external_llm_share', 0):.0%} of turns"
            ),
            "confidence": "medium",
            "effort": "medium",
            "owner": "platform",
            "evidence": [
                "config/models.yaml egress classes",
                "config/finops_model.yaml external_llm_share",
            ],
        }
    )
    for item in items:
        item["dedupe_key"] = f"{item.pop('key')}:{day}"
    return items


async def _model_rewrite(
    services: Services,
    session: AsyncSession,
    candidates: list[dict[str, Any]],
    *,
    trace_id: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Ask the local model to improve wording only; evidence stays deterministic."""
    if not candidates:
        return candidates, None
    payload = [
        {
            "id": item["dedupe_key"],
            "title": item["title"],
            "recommendation": item["recommendation"],
            "area": item["area"],
            "evidence": item["evidence"],
        }
        for item in candidates
    ]
    messages = [
        {
            "role": "system",
            "content": (
                "You are an operations analyst. Rewrite the supplied advisory titles and "
                "recommendations so they are concise and specific. Do not add new facts, "
                "numbers, clinical advice, patient data or promises. Keep every id and every "
                "evidence string unchanged. Return JSON only: "
                '{"items":[{"id":"...","title":"...","recommendation":"..."}]}'
            ),
        },
        {"role": "user", "content": json.dumps({"items": payload}, separators=(",", ":"))},
    ]
    gateway = LlmGateway(services.settings, services.models_config)
    try:
        result = await gateway.complete(
            purpose="insights",
            messages=messages,
            max_tokens=1200,
            temperature=0.2,
            trace_id=trace_id,
        )
    except LlmGatewayError:
        return candidates, None
    try:
        raw = result.content.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[raw.find("{") :]
        parsed = json.loads(raw)
        by_id = {
            str(item["id"]): item
            for item in parsed.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
    except (ValueError, TypeError, AttributeError):
        return candidates, None
    rewritten = []
    for item in candidates:
        update = by_id.get(item["dedupe_key"])
        if update is None:
            rewritten.append(item)
            continue
        title = str(update.get("title", "")).strip()[:200]
        recommendation = str(update.get("recommendation", "")).strip()[:1200]
        rewritten.append(
            {
                **item,
                "title": title or item["title"],
                "recommendation": recommendation or item["recommendation"],
            }
        )
    await UsageRepository(session).record(
        purpose="insights",
        model_alias=result.model_alias,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=services.model_cost(
            result.model_alias, result.prompt_tokens, result.completion_tokens
        ),
        trace_id=trace_id,
        session_id=None,
        traffic_class="real",
        gateway_request_id=result.gateway_request_id,
    )
    return rewritten, result.model_alias


async def generate_insights(services: Services) -> dict[str, Any]:
    async with _job(services, "analytics.insights") as (session, run):
        end = dt.datetime.now(dt.UTC)
        start = end - dt.timedelta(days=INSIGHT_WINDOW_DAYS)
        repo = AnalyticsRepository(session)
        counts = await repo.overview_counts(start=start, end=end)
        actions = await repo.audit_action_counts(start=start, end=end)
        consents = await repo.consent_counts()
        usage = await UsageRepository(session).summary(start=start, end=end)
        latest_eval = await session.scalar(
            select(EvalRun).order_by(EvalRun.created_at.desc()).limit(1)
        )
        latest_reconciliation = await session.scalar(
            select(SpendReconciliation).order_by(SpendReconciliation.created_at.desc()).limit(1)
        )
        candidates = _deterministic_candidates(
            services,
            counts=counts,
            actions=actions,
            consents=consents,
            usage=usage,
            latest_eval=latest_eval,
            latest_reconciliation=latest_reconciliation,
            window_end=end,
        )
        trace_id = f"job-insights-{uuid.uuid4().hex}"[:64]
        rewritten, model_alias = await _model_rewrite(
            services, session, candidates, trace_id=trace_id
        )
        generator = "local_model" if model_alias else "deterministic_rules"
        created = updated = skipped = 0
        for item in rewritten:
            existing = await session.scalar(
                select(Insight).where(Insight.dedupe_key == item["dedupe_key"])
            )
            if existing is not None:
                if existing.status != "proposed":
                    skipped += 1
                    continue
                existing.title = item["title"]
                existing.recommendation = item["recommendation"]
                existing.impact = item["impact"]
                existing.confidence = item["confidence"]
                existing.effort = item["effort"]
                existing.owner = item["owner"]
                existing.evidence = item["evidence"]
                existing.generator = generator
                existing.model_alias = model_alias
                existing.ai_generated = bool(model_alias)
                updated += 1
                continue
            session.add(
                Insight(
                    dedupe_key=item["dedupe_key"],
                    area=item["area"],
                    title=item["title"],
                    recommendation=item["recommendation"],
                    impact=item["impact"],
                    confidence=item["confidence"],
                    effort=item["effort"],
                    owner=item["owner"],
                    evidence=item["evidence"],
                    generator=generator,
                    model_alias=model_alias,
                    ai_generated=bool(model_alias),
                    status="proposed",
                    window_start=start,
                    window_end=end,
                )
            )
            created += 1
        expiry = end - dt.timedelta(days=INSIGHT_EXPIRY_DAYS)
        stale = list(
            await session.scalars(
                select(Insight).where(Insight.status == "proposed", Insight.created_at < expiry)
            )
        )
        for expired_insight in stale:
            expired_insight.status = "expired"
        AuditRepository(session).append(
            actor_subject="system:analytics",
            actor_role="service",
            action="analytics.insights_generated",
            resource_type="insight_batch",
            metadata={
                "generator": generator,
                "model_alias": model_alias,
                "created": created,
                "updated": updated,
                "skipped_decided": skipped,
                "expired": len(stale),
            },
        )
        run.detail = {
            "generator": generator,
            "created": created,
            "updated": updated,
            "skipped_decided": skipped,
            "expired": len(stale),
        }
        return dict(run.detail)


async def decide_insight(
    session: AsyncSession,
    *,
    insight_id: uuid.UUID,
    status: str,
    decided_by: str,
    note: str | None,
    trace_id: str | None,
) -> Insight:
    from sahyog_common.errors import ProblemError

    insight = await session.get(Insight, insight_id)
    if insight is None:
        raise ProblemError(404, "insight_not_found", "Not found", "No such insight.")
    if status not in {"accepted", "rejected"}:
        raise ProblemError(
            422, "invalid_decision", "Invalid decision", "Decide accepted or rejected."
        )
    insight.status = status
    insight.decided_by = decided_by[:200]
    insight.decided_at = dt.datetime.now(dt.UTC)
    insight.decision_note = (note or "")[:500] or None
    AuditRepository(session).append(
        actor_subject=decided_by,
        actor_role="admin",
        action=f"analytics.insight_{status}",
        resource_type="insight",
        resource_id=str(insight.id),
        trace_id=trace_id,
        metadata={"dedupe_key": insight.dedupe_key, "area": insight.area, "note": note or ""},
    )
    await session.flush()
    return insight


def insight_out(insight: Insight) -> dict[str, Any]:
    return {
        "id": str(insight.id),
        "dedupe_key": insight.dedupe_key,
        "area": insight.area,
        "title": insight.title,
        "recommendation": insight.recommendation,
        "impact": insight.impact,
        "confidence": insight.confidence,
        "effort": insight.effort,
        "owner": insight.owner,
        "evidence": insight.evidence,
        "generator": insight.generator,
        "model_alias": insight.model_alias,
        "ai_generated": insight.ai_generated,
        "status": insight.status,
        "decided_by": insight.decided_by,
        "decided_at": insight.decided_at.isoformat() if insight.decided_at else None,
        "decision_note": insight.decision_note,
        "window_start": insight.window_start.isoformat(),
        "window_end": insight.window_end.isoformat(),
        "created_at": insight.created_at.isoformat() if insight.created_at else None,
        "advisory": True,
    }


def _audit_line(event: AuditEvent) -> str:
    payload = {
        "id": str(event.id),
        "created_at": event.created_at.isoformat() if event.created_at else "",
        "actor_subject": event.actor_subject,
        "actor_role": event.actor_role,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "patient_id": str(event.patient_id) if event.patient_id else None,
        "trace_id": event.trace_id,
        "metadata": event.event_metadata,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


async def create_audit_anchor(services: Services) -> dict[str, Any]:
    async with _job(services, "analytics.audit_anchor") as (session, run):
        if not services.settings.s3_configured:
            run.detail = {"status": "skipped_unconfigured", "reason": "s3_unconfigured"}
            return dict(run.detail)
        rows = list(
            await session.scalars(select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id))
        )
        hasher = hashlib.sha256()
        for row in rows:
            hasher.update(_audit_line(row).encode("utf-8"))
            hasher.update(b"\n")
        digest = hasher.hexdigest()
        bucket = services.settings.s3_bucket_anchors
        previous: dict[str, Any] | None = None
        try:
            raw = await services.storage.get(key="anchors/latest.json", bucket=bucket)
            parsed = json.loads(raw.decode("utf-8"))
            if isinstance(parsed, dict):
                previous = parsed
        except (StorageError, ValueError):
            previous = None
        now = dt.datetime.now(dt.UTC)
        anchor = {
            "version": 1,
            "created_at": now.isoformat(),
            "event_count": len(rows),
            "first_event_at": rows[0].created_at.isoformat() if rows else None,
            "last_event_at": rows[-1].created_at.isoformat() if rows else None,
            "digest_sha256": digest,
            "previous_digest_sha256": previous.get("digest_sha256") if previous else None,
            "previous_event_count": previous.get("event_count") if previous else None,
            "scope": (
                "Digest over audit rows present at capture. This is a point-in-time anchor, "
                "not a per-row hash chain and not proof of completeness."
            ),
        }
        data = json.dumps(anchor, indent=2, sort_keys=True).encode("utf-8")
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        await services.storage.put(
            key=f"anchors/{stamp}.json", data=data, content_type="application/json", bucket=bucket
        )
        await services.storage.put(
            key="anchors/latest.json",
            data=data,
            content_type="application/json",
            bucket=bucket,
        )
        AuditRepository(session).append(
            actor_subject="system:analytics",
            actor_role="service",
            action="audit.anchor_created",
            resource_type="audit_anchor",
            resource_id=stamp,
            metadata={
                "event_count": len(rows),
                "digest_sha256": digest,
                "previous_digest_sha256": anchor["previous_digest_sha256"],
                "bucket": bucket,
            },
        )
        run.detail = {
            "event_count": len(rows),
            "digest_sha256": digest,
            "key": f"anchors/{stamp}.json",
            "previous_digest_sha256": anchor["previous_digest_sha256"],
        }
        return dict(run.detail)


async def _send_alert(
    services: Services,
    session: AsyncSession,
    *,
    alert: str,
    action: str,
) -> None:
    if not services.settings.notify_ops_subject:
        return
    recent = await session.scalar(
        select(AuditEvent.id)
        .where(
            AuditEvent.action == action,
            AuditEvent.created_at >= dt.datetime.now(dt.UTC) - dt.timedelta(hours=6),
        )
        .limit(1)
    )
    if recent is not None:
        return
    try:
        await NotificationService(services, session).send(
            template_id="ops_alert",
            recipient_subject=services.settings.notify_ops_subject,
            recipient_role="admin",
            patient_id=None,
            locale="en-IN",
            data={"alert": alert},
            actor_subject="system:analytics",
            actor_role="service",
            requested_channels=["in_app", "email"],
            emergency=True,
        )
    except Exception:  # noqa: BLE001 - alerting must not fail the job
        logger.warning(
            "operations alert could not be queued",
            extra={"event": "analytics.alert_failed"},
        )


async def check_staleness(services: Services) -> dict[str, Any]:
    async with _job(services, "analytics.staleness") as (session, run):
        now = dt.datetime.now(dt.UTC)
        snapshot = await session.scalar(
            select(AnalyticsSnapshot).order_by(AnalyticsSnapshot.captured_at.desc()).limit(1)
        )
        reconciliation = await session.scalar(
            select(SpendReconciliation).order_by(SpendReconciliation.created_at.desc()).limit(1)
        )
        alerts: list[str] = []
        snapshot_age = (
            (now - snapshot.captured_at).total_seconds() / 3600 if snapshot is not None else None
        )
        reconciliation_age = (
            (now - reconciliation.created_at).total_seconds() / 3600
            if reconciliation is not None
            else None
        )
        if snapshot_age is None or snapshot_age > SNAPSHOT_STALE_HOURS:
            alerts.append(
                "Analytics snapshots are stale"
                + (
                    f" ({snapshot_age:.1f}h old)."
                    if snapshot_age is not None
                    else " (none recorded)."
                )
            )
            await _send_alert(
                services,
                session,
                alert=alerts[-1],
                action="analytics.snapshot_stale_alerted",
            )
            AuditRepository(session).append(
                actor_subject="system:analytics",
                actor_role="service",
                action="analytics.snapshot_stale_alerted",
                resource_type="analytics_snapshot",
                metadata={"age_hours": snapshot_age},
            )
        if reconciliation_age is None or reconciliation_age > RECONCILIATION_STALE_HOURS:
            alerts.append(
                "FinOps reconciliation is stale"
                + (
                    f" ({reconciliation_age:.1f}h old)."
                    if reconciliation_age is not None
                    else " (none recorded)."
                )
            )
            await _send_alert(
                services,
                session,
                alert=alerts[-1],
                action="finops.reconciliation_stale_alerted",
            )
            AuditRepository(session).append(
                actor_subject="system:finops",
                actor_role="service",
                action="finops.reconciliation_stale_alerted",
                resource_type="spend_reconciliation",
                metadata={"age_hours": reconciliation_age},
            )
        run.detail = {
            "snapshot_age_hours": snapshot_age,
            "reconciliation_age_hours": reconciliation_age,
            "alerts": alerts,
        }
        return dict(run.detail)


async def run_finops_reconciliation(services: Services) -> dict[str, Any]:
    async with _job(services, "finops.reconcile") as (session, run):
        record = await reconcile_spend(services, session, window_hours=24)
        detail = {
            "status": record.status,
            "variance_pct": record.variance_pct,
            "app_calls": record.app_calls,
            "gateway_calls": record.gateway_calls,
            "matched_calls": record.matched_calls,
        }
        run.detail = detail
        return detail
