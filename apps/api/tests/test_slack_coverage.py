"""G-06/G-07: Slack verify path, coverage metric, honest fallback; G-24 retention wiring."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import Settings
from app.core.ports import DeliveryError
from app.modules.memory import retention
from app.modules.notifications import jobs as notification_jobs
from app.modules.notifications.router import (
    _SLACK_MEMBER_ID,
    _deliver_verification_code,
    me_router,
    router,
)
from app.modules.notifications.service import NotificationService
from app.repositories.models import ContactChannel, GovernanceSetting, Patient

NOW = dt.datetime(2026, 10, 31, tzinfo=dt.UTC)
WORKSPACE = "TPATIENT"


def _contact(**kwargs: Any) -> ContactChannel:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "subject": "p1",
        "channel": "slack_patient",
        "address": "U0ABC12345",
        "verified": True,
        "opt_in": True,
        "workspace_id": WORKSPACE,
        "verified_at": NOW - dt.timedelta(days=10),
    }
    values.update(kwargs)
    return ContactChannel(**values)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "verified"),
        ({"verified": False}, "unverified"),
        ({"workspace_id": "TOTHER"}, "workspace_mismatch"),
        ({"verified_at": None}, "verified_at_missing"),
        ({"verified_at": NOW - dt.timedelta(days=200)}, "stale"),
    ],
)
def test_classify_slack_contact(overrides: dict[str, Any], expected: str) -> None:
    result = notification_jobs.classify_slack_contact(
        _contact(**overrides), expected_workspace=WORKSPACE, now=NOW
    )
    assert result == expected


def test_workspace_unconfigured_never_counts_as_verified() -> None:
    assert (
        notification_jobs.classify_slack_contact(_contact(), expected_workspace="", now=NOW)
        == "workspace_unconfigured"
    )


class _CoverageSession:
    def __init__(self, contacts: list[ContactChannel], metadata_patient_ids: list[Any]) -> None:
        self._batches = [contacts, metadata_patient_ids]

    async def scalars(self, _statement: object) -> list[Any]:
        return self._batches.pop(0)


async def _coverage(contacts: list[ContactChannel], metadata: list[Any] | None = None) -> dict:
    return await notification_jobs.slack_patient_coverage(
        _CoverageSession(contacts, metadata or []),  # type: ignore[arg-type]
        expected_workspace=WORKSPACE,
        adapter_configured=False,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_empty_population_is_not_evidence() -> None:
    result = await _coverage([])
    assert result["status"] == "no_opted_in_contacts"
    assert result["coverage_percent"] is None
    assert result["meets_target"] is False


@pytest.mark.asyncio
async def test_coverage_below_target_lists_reasons() -> None:
    result = await _coverage(
        [_contact(), _contact(verified=False), _contact(verified_at=NOW - dt.timedelta(days=400))]
    )
    assert result["opted_in"] == 3
    assert result["verified"] == 1
    assert result["coverage_percent"] == 33.3
    assert result["status"] == "below_target"
    assert result["not_covered"]["unverified"] == 1
    assert result["not_covered"]["stale"] == 1
    assert result["delivery_ready"] is False


@pytest.mark.asyncio
async def test_full_coverage_meets_target_but_reports_delivery_not_ready() -> None:
    result = await _coverage([_contact(), _contact()])
    assert result["status"] == "complete"
    assert result["coverage_percent"] == 100.0
    assert result["meets_target"] is True
    assert result["delivery_ready"] is False  # adapter_configured=False in helper


@pytest.mark.asyncio
async def test_metadata_only_patients_are_counted_but_not_covered() -> None:
    covered = uuid.uuid4()
    orphan = uuid.uuid4()
    result = await _coverage([_contact(patient_id=covered)], [covered, orphan])
    assert result["metadata_only_unverified"] == 1
    assert result["status"] == "complete"


def test_routes_declared() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert "/api/v1/notifications/slack-coverage" in paths
    me_paths = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()))))
        for route in me_router.routes
    }
    assert ("/api/v1/me/contacts", ("POST",)) in me_paths
    # slack-coverage must be matched before the uuid route.
    ordered = [getattr(route, "path", "") for route in router.routes]
    assert ordered.index("/api/v1/notifications/slack-coverage") < ordered.index(
        "/api/v1/notifications/{notification_id}"
    )


def test_self_registration_rejects_channel_ids() -> None:
    assert _SLACK_MEMBER_ID.match("U0CDT655E1X")
    assert _SLACK_MEMBER_ID.match("W012AB3CD4")
    assert not _SLACK_MEMBER_ID.match("C0123456789")
    assert not _SLACK_MEMBER_ID.match("u0cdt655e1x")
    assert not _SLACK_MEMBER_ID.match("U1")


class _Dispatcher:
    def __init__(self, *, configured: bool, error: Exception | None = None) -> None:
        self._configured = configured
        self._error = error
        self.sent: list[dict[str, str]] = []

    def configured(self, channel: str) -> bool:
        return self._configured

    async def send(self, **kwargs: str) -> str:
        if self._error is not None:
            raise self._error
        self.sent.append(kwargs)
        return "ts"


def _services(dispatcher: Any, *, external: bool = True) -> Any:
    return SimpleNamespace(
        settings=SimpleNamespace(notify_send_external=external),
        notifications=dispatcher,
    )


@pytest.mark.asyncio
async def test_verification_code_not_delivered_when_unconfigured() -> None:
    contact = _contact()
    assert await _deliver_verification_code(
        _services(_Dispatcher(configured=False)), contact, "123456"
    ) == ("unconfigured", None)
    assert await _deliver_verification_code(_services(None), contact, "123456") == (
        "unconfigured",
        None,
    )
    assert await _deliver_verification_code(
        _services(_Dispatcher(configured=True), external=False), contact, "123456"
    ) == ("external_disabled", None)


@pytest.mark.asyncio
async def test_verification_code_sent_over_own_channel_without_clinical_text() -> None:
    dispatcher = _Dispatcher(configured=True)
    result = await _deliver_verification_code(_services(dispatcher), _contact(), "123456")
    assert result == ("sent", None)
    assert dispatcher.sent[0]["channel"] == "slack_patient"
    assert dispatcher.sent[0]["address"] == "U0ABC12345"
    assert "123456" in dispatcher.sent[0]["body"]


@pytest.mark.asyncio
async def test_verification_delivery_failure_is_reported() -> None:
    failing = _Dispatcher(configured=True, error=DeliveryError("slack_rejected"))
    assert await _deliver_verification_code(_services(failing), _contact(), "123456") == (
        "failed",
        "slack_rejected",
    )


@pytest.mark.asyncio
async def test_patient_metadata_fallback_is_unverified_and_not_opted_in() -> None:
    patient = Patient(id=uuid.uuid4(), slack_user_id="U0META12345", notify_email="a@example.test")

    class _Session:
        async def get(self, _model: object, _pk: object) -> Patient:
            return patient

    service = NotificationService.__new__(NotificationService)
    service._session = _Session()  # type: ignore[assignment]
    service._services = SimpleNamespace(  # type: ignore[assignment]
        settings=Settings(_env_file=None, app_env="test", slack_patient_workspace_id=WORKSPACE)
    )
    for channel in ("slack_patient", "email"):
        contact = await service._contact_from_patient_metadata(
            channel=channel, recipient_subject="p1", patient_id=patient.id
        )
        assert contact is not None
        assert contact.verified is False
        assert contact.opt_in is False


# --- G-24 retention wiring -------------------------------------------------------------


class _GovSession:
    def __init__(self, rows: dict[str, GovernanceSetting]) -> None:
        self._rows = rows

    async def get(self, _model: object, key: str) -> GovernanceSetting | None:
        return self._rows.get(key)


def _setting(key: str, value: Any) -> GovernanceSetting:
    return GovernanceSetting(key=key, value={"value": value})


@pytest.mark.asyncio
async def test_governance_override_reads_valid_rows_only() -> None:
    session = _GovSession(
        {
            "memory_retention_days": _setting("memory_retention_days", 30),
            "chat_retention_days": _setting("chat_retention_days", 99999),
        }
    )
    assert await retention.governance_override_days(session, "memory_retention_days") == 30  # type: ignore[arg-type]
    assert await retention.governance_override_days(session, "chat_retention_days") is None  # type: ignore[arg-type]
    assert await retention.governance_override_days(session, "missing") is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_memory_retention_defaults_when_no_governance_row() -> None:
    assert await retention.effective_memory_retention_days(_GovSession({})) == (  # type: ignore[arg-type]
        180,
        "default",
    )
    session = _GovSession({"memory_retention_days": _setting("memory_retention_days", 14)})
    assert await retention.effective_memory_retention_days(session) == (14, "governance")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_chat_retention_override_can_only_shorten_config() -> None:
    longer = _GovSession({"chat_retention_days": _setting("chat_retention_days", 365)})
    shorter = _GovSession({"chat_retention_days": _setting("chat_retention_days", 7)})
    assert await retention.effective_chat_retention_days(longer, 30) == 30  # type: ignore[arg-type]
    assert await retention.effective_chat_retention_days(shorter, 30) == 7  # type: ignore[arg-type]
    assert await retention.effective_chat_retention_days(_GovSession({}), 30) == 30  # type: ignore[arg-type]


def test_scheduler_registers_memory_retention_cron() -> None:
    from app.scheduler import WorkerSettings

    assert "purge_expired_memory" in {fn.__name__ for fn in WorkerSettings.functions}
    assert "purge_expired_memory" in {job.coroutine.__name__ for job in WorkerSettings.cron_jobs}


class _JobSession:
    """Fake session: scalars() yields due-list, coverage contacts, then metadata-only ids."""

    def __init__(self, batches: list[list[Any]]) -> None:
        self._batches = batches
        self.committed = False

    def add(self, _obj: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def scalars(self, _statement: object) -> list[Any]:
        return self._batches.pop(0)

    async def __aenter__(self) -> _JobSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _NullAudit:
    events: list[dict[str, Any]] = []

    def __init__(self, _session: Any) -> None:
        pass

    def append(self, **kwargs: Any) -> None:
        _NullAudit.events.append(kwargs)


@pytest.mark.asyncio
async def test_scan_alerts_when_opted_in_coverage_below_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.analytics.jobs as analytics_jobs

    session = _JobSession([[], [_contact(), _contact(verified=False)], []])
    services = SimpleNamespace(
        db=SimpleNamespace(sessionmaker=lambda: session),
        settings=SimpleNamespace(
            slack_patient_workspace_id=WORKSPACE, slack_patient_configured=True
        ),
    )
    alerts: list[dict[str, Any]] = []

    async def _fake_alert(_services: Any, _session: Any, *, alert: str, action: str) -> None:
        alerts.append({"alert": alert, "action": action})

    _NullAudit.events = []
    monkeypatch.setattr(notification_jobs, "AuditRepository", _NullAudit)
    monkeypatch.setattr(analytics_jobs, "_send_alert", _fake_alert)

    detail = await notification_jobs.scan_contact_reverification(services)  # type: ignore[arg-type]

    assert detail["slack_patient_coverage"]["status"] == "below_target"
    assert len(alerts) == 1
    assert alerts[0]["action"] == "notifications.slack_coverage_alerted"
    assert "50.0%" in alerts[0]["alert"]
    assert any(e["action"] == "notifications.slack_coverage_alerted" for e in _NullAudit.events)


@pytest.mark.asyncio
async def test_scan_does_not_alert_on_empty_or_complete_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.analytics.jobs as analytics_jobs

    alerts: list[str] = []

    async def _fake_alert(*_a: Any, **_k: Any) -> None:
        alerts.append("x")

    monkeypatch.setattr(notification_jobs, "AuditRepository", _NullAudit)
    monkeypatch.setattr(analytics_jobs, "_send_alert", _fake_alert)
    for contacts in ([], [_contact()]):
        session = _JobSession([[], contacts, []])
        services = SimpleNamespace(
            db=SimpleNamespace(sessionmaker=lambda s=session: s),
            settings=SimpleNamespace(
                slack_patient_workspace_id=WORKSPACE, slack_patient_configured=True
            ),
        )
        await notification_jobs.scan_contact_reverification(services)  # type: ignore[arg-type]
    assert alerts == []
