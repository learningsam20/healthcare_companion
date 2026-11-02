from __future__ import annotations

import httpx
import pytest
from app.core.config import Settings
from app.core.ports import DeliveryError
from app.integrations.notifications import NotificationDispatcher, SlackAdapter

SLACK_ENV = (
    "SLACK_BOT_TOKEN",
    "SLACK_STAFF_BOT_TOKEN",
    "SLACK_PATIENT_BOT_TOKEN",
    "SLACK_STAFF_WORKSPACE_ID",
    "SLACK_PATIENT_WORKSPACE_ID",
    "SLACK_ALLOWED_CHANNELS",
    "SLACK_PATIENT_ALLOWED_CHANNELS",
)


@pytest.fixture(autouse=True)
def _clear_slack_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force empty process env so a developer .env cannot leak into unit tests.
    for key in SLACK_ENV:
        monkeypatch.setenv(key, "")


def _settings(**kwargs: object) -> Settings:
    values = {
        "slack_bot_token": "",
        "slack_staff_bot_token": "",
        "slack_patient_bot_token": "",
        "slack_staff_workspace_id": "",
        "slack_patient_workspace_id": "",
        "slack_allowed_channels": "",
        "slack_patient_allowed_channels": "",
    }
    values.update(kwargs)  # type: ignore[arg-type]
    return Settings(_env_file=None, app_env="test", **values)  # type: ignore[arg-type]


def test_staff_and_patient_tokens_are_separate() -> None:
    settings = _settings(
        slack_staff_bot_token="xoxb-staff",
        slack_patient_bot_token="xoxb-patient",
        slack_staff_workspace_id="TSTAFF",
        slack_patient_workspace_id="TPATIENT",
        slack_allowed_channels="CSTAFF",
    )
    adapter = SlackAdapter(settings)
    assert adapter.token_for("slack_staff") == "xoxb-staff"
    assert adapter.token_for("slack_patient") == "xoxb-patient"
    assert settings.slack_staff_configured
    assert settings.slack_patient_configured


def test_legacy_bot_token_aliases_staff_only() -> None:
    settings = _settings(
        slack_bot_token="xoxb-legacy",
        slack_staff_bot_token="",
        slack_patient_bot_token="",
        slack_staff_workspace_id="TSTAFF",
        slack_allowed_channels="CSTAFF",
        slack_patient_workspace_id="TPATIENT",
    )
    assert settings.resolved_slack_staff_bot_token == "xoxb-legacy"
    assert settings.slack_staff_configured
    assert not settings.slack_patient_configured


@pytest.mark.asyncio
async def test_dispatcher_uses_channel_token(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(
        slack_staff_bot_token="xoxb-staff",
        slack_patient_bot_token="xoxb-patient",
        slack_staff_workspace_id="TSTAFF",
        slack_patient_workspace_id="TPATIENT",
        slack_allowed_channels="CSTAFF",
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        seen.append(auth)
        return httpx.Response(200, json={"ok": True, "ts": "1.2"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.integrations.notifications.httpx.AsyncClient", fake_client)
    dispatcher = NotificationDispatcher(settings)
    await dispatcher.send(
        channel="slack_staff", address="CSTAFF", subject="Ops", body="queue alert"
    )
    await dispatcher.send(
        channel="slack_patient", address="U123", subject="Notice", body="message ready"
    )
    assert seen == ["Bearer xoxb-staff", "Bearer xoxb-patient"]


@pytest.mark.asyncio
async def test_missing_patient_token_fails_closed() -> None:
    settings = _settings(
        slack_staff_bot_token="xoxb-staff",
        slack_patient_bot_token="",
        slack_staff_workspace_id="TSTAFF",
        slack_allowed_channels="CSTAFF",
        slack_patient_workspace_id="TPATIENT",
    )
    dispatcher = NotificationDispatcher(settings)
    with pytest.raises(DeliveryError) as exc:
        await dispatcher.send(
            channel="slack_patient", address="U123", subject="x", body="y"
        )
    assert exc.value.code == "slack_unconfigured"
