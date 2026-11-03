from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import yaml
from app.core.config import Settings
from app.integrations.notifications import EmailAdapter, NotificationDispatcher
from app.modules.notifications.format import email_html, slack_message
from app.modules.notifications.service import (
    ALLOWED_TEMPLATE_DATA,
    NotificationService,
    in_quiet_hours,
    quiet_hours_end,
)

ROOT = Path(__file__).resolve().parents[3]
CHANNELS_CONFIG = ROOT / "config" / "notifications.yaml"
COPY_CONFIG = ROOT / "config" / "i18n" / "notifications.yaml"
IST = ZoneInfo("Asia/Kolkata")


def _config() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(CHANNELS_CONFIG.read_text(encoding="utf-8")))


def _copy() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(COPY_CONFIG.read_text(encoding="utf-8")))


def test_every_template_has_all_three_languages() -> None:
    copy = _copy()["templates"]
    for template in _config()["templates"]:
        entry = copy.get(template["id"])
        assert entry is not None, template["id"]
        assert {"en", "hi", "mr"} <= set(entry), template["id"]
        for language in ("en", "hi", "mr"):
            text = entry[language]
            assert text["subject"].strip()
            assert text["intro"].strip()
            assert text["action_label"].strip()
            assert text["facts"]


def test_template_copy_uses_only_allowed_placeholders() -> None:
    placeholders = re.compile(r"\{([a-z_]+)\}")
    for template_id, entry in _copy()["templates"].items():
        for language, text in entry.items():
            used = set(
                placeholders.findall(text["subject"])
                + placeholders.findall(text.get("subject_detail") or "")
                + placeholders.findall(text["intro"])
                + placeholders.findall(text.get("footer") or "")
                + placeholders.findall(text.get("action_label") or "")
            )
            assert used <= ALLOWED_TEMPLATE_DATA, f"{template_id}/{language}: {used}"
            for fact in text["facts"]:
                assert fact["key"] in ALLOWED_TEMPLATE_DATA, f"{template_id}/{language}"


def test_email_attachments_allowed_for_operational_kinds() -> None:
    email = _config()["channels"]["email"]
    assert email["allow_attachments"] is True
    assert "ics" in email["allowed_attachment_kinds"]


def test_templates_never_claim_clinical_detail() -> None:
    for template in _config()["templates"]:
        assert template["clinical_detail"] is False
        assert "in_app" in template["channels"]


def test_quiet_hours_overnight_window() -> None:
    assert in_quiet_hours(
        now=dt.datetime(2026, 10, 25, 22, 0, tzinfo=IST),
        start="21:00",
        end="08:00",
        timezone="Asia/Kolkata",
    )
    assert in_quiet_hours(
        now=dt.datetime(2026, 10, 25, 6, 30, tzinfo=IST),
        start="21:00",
        end="08:00",
        timezone="Asia/Kolkata",
    )
    assert not in_quiet_hours(
        now=dt.datetime(2026, 10, 25, 12, 0, tzinfo=IST),
        start="21:00",
        end="08:00",
        timezone="Asia/Kolkata",
    )


def test_quiet_hours_end_is_next_morning() -> None:
    end = quiet_hours_end(
        now=dt.datetime(2026, 10, 25, 22, 0, tzinfo=IST),
        start="21:00",
        end="08:00",
        timezone="Asia/Kolkata",
    )
    assert end == dt.datetime(2026, 10, 26, 8, 0, tzinfo=IST)


def test_quiet_hours_end_within_morning_window() -> None:
    end = quiet_hours_end(
        now=dt.datetime(2026, 10, 25, 6, 30, tzinfo=IST),
        start="21:00",
        end="08:00",
        timezone="Asia/Kolkata",
    )
    assert end == dt.datetime(2026, 10, 25, 8, 0, tzinfo=IST)


def test_daytime_window() -> None:
    assert in_quiet_hours(
        now=dt.datetime(2026, 10, 25, 13, 0, tzinfo=IST),
        start="12:00",
        end="14:00",
        timezone="Asia/Kolkata",
    )
    assert not in_quiet_hours(
        now=dt.datetime(2026, 10, 25, 14, 0, tzinfo=IST),
        start="12:00",
        end="14:00",
        timezone="Asia/Kolkata",
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [("21:00", "08:00"), ("09:30", "10:15"), ("00:00", "00:01")],
)
def test_quiet_hours_end_is_after_now(start: str, end: str) -> None:
    now = dt.datetime(2026, 10, 25, 3, 0, tzinfo=IST)
    assert quiet_hours_end(now=now, start=start, end=end, timezone="Asia/Kolkata") > now


def _renderer() -> NotificationService:
    service = NotificationService.__new__(NotificationService)
    service._config = _config()
    service._copy = _copy()
    return service


def test_rendered_notice_includes_facts_reference_and_action() -> None:
    subject, body, presentation = _renderer().render(
        "booking_confirmed",
        "en-IN",
        {
            "doctor_name": "Dr Ananya Rao",
            "clinic_code": "BANER",
            "starts_at": "05 Nov 2026, 09:30 AM",
            "duration_minutes": "20",
            "appointment_id": "12345678-aaaa-bbbb-cccc-ddddeeeeffff",
            "action_url": "http://localhost:5705/appointments",
        },
    )
    assert subject.startswith("Appointment confirmed — Dr Ananya Rao")
    assert "BANER" in subject
    assert "Doctor: Dr Ananya Rao" in body
    assert "Duration: 20 minutes" in body
    assert "Reference: 12345678" in body
    assert "Open appointment: http://localhost:5705/appointments" in body
    assert presentation["action_url"].endswith("/appointments")
    assert presentation["facts"][0] == {"label": "Doctor", "value": "Dr Ananya Rao"}


def test_empty_subject_parts_are_dropped() -> None:
    subject, body, presentation = _renderer().render(
        "ops_alert",
        "en-IN",
        {
            "alert": "Analytics snapshots are stale (none recorded).",
            "alert_summary": "Analytics snapshots are stale (none recorded).",
            "action_url": "http://localhost:5705/analytics",
        },
    )
    assert subject == "Operations alert — Analytics snapshots are stale (none recorded)."
    assert "Priority:" not in body
    assert presentation["action_label"] == "Open in Sahyog"
    assert "http://localhost:5705/analytics" in body
    bare, _body, _presentation = _renderer().render(
        "booking_confirmed",
        "hi-IN",
        {"starts_at": "05 Nov 2026, 09:30 AM", "clinic_code": "BANER"},
    )
    assert bare == "अपॉइंटमेंट पक्का हुआ — 05 Nov 2026, 09:30 AM · BANER"
    assert "·  ·" not in bare


def test_email_and_slack_escape_values_and_carry_the_action() -> None:
    presentation = {
        "intro": "Your appointment is confirmed.",
        "footer": "Open it to reschedule.",
        "action_label": "Open appointment",
        "action_url": "http://localhost:5705/appointments",
        "facts": [{"label": "Doctor", "value": "Dr <Rao> & Shah"}],
    }
    html = email_html("Appointment confirmed", "plain", presentation)
    assert "Dr &lt;Rao&gt; &amp; Shah" in html
    assert 'href="http://localhost:5705/appointments"' in html
    assert "<script>" not in html
    slack = slack_message("Appointment confirmed", "plain", presentation)
    assert slack["blocks"][0]["type"] == "header"
    assert slack["blocks"][-1]["elements"][0]["url"].endswith("/appointments")
    doctor = next(
        field["text"]
        for block in slack["blocks"]
        if block.get("fields")
        for field in block["fields"]
    )
    assert "Dr &lt;Rao&gt; &amp; Shah" in doctor


@pytest.mark.asyncio
async def test_dispatcher_posts_slack_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode())
        return httpx.Response(200, json={"ok": True, "ts": "1.2"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.integrations.notifications.httpx.AsyncClient", fake_client)
    settings = Settings(
        _env_file=None,
        app_env="test",
        slack_staff_bot_token="xoxb-staff",
        slack_staff_workspace_id="TSTAFF",
        slack_allowed_channels="CSTAFF",
    )
    await NotificationDispatcher(settings).send(
        channel="slack_staff",
        address="CSTAFF",
        subject="Staff handoff — high · BANER",
        body="A staff handoff is waiting.",
        presentation={
            "intro": "A staff handoff is waiting for acknowledgement.",
            "footer": "Assign it before the SLA.",
            "action_label": "Open escalations",
            "action_url": "http://localhost:5705/escalations",
            "facts": [{"label": "Clinic", "value": "BANER"}, {"label": "Priority", "value": "high"}],
        },
    )
    import json

    payload = json.loads(seen[0])
    assert payload["blocks"][-1]["elements"][0]["url"].endswith("/escalations")
    assert any(block.get("fields") for block in payload["blocks"])


@pytest.mark.asyncio
async def test_email_includes_html_alternative(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_send(message: Any, **_kwargs: object) -> tuple[object, list[str]]:
        captured["message"] = message
        return ({}, ["250 ok"])

    monkeypatch.setattr("app.integrations.notifications.aiosmtplib.send", fake_send)
    settings = Settings(
        _env_file=None,
        app_env="test",
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_auth_mode="password",
        smtp_password="secret",
        email_from="care@example.test",
    )
    await EmailAdapter(settings).send(
        address="patient@example.test",
        subject="Appointment confirmed — Dr Rao",
        body="Your appointment is confirmed.",
        presentation={
            "intro": "Your appointment is confirmed.",
            "footer": "Open it to reschedule.",
            "action_label": "Open appointment",
            "action_url": "http://localhost:5705/appointments",
            "facts": [{"label": "When", "value": "05 Nov 2026, 09:30 AM"}],
        },
    )
    message = captured["message"]
    assert message["Subject"] == "Appointment confirmed — Dr Rao"
    html_parts = [
        part.get_content()
        for part in message.walk()
        if part.get_content_type() == "text/html"
    ]
    assert html_parts
    assert "05 Nov 2026, 09:30 AM" in html_parts[0]
    assert "Open appointment" in html_parts[0]
