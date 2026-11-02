from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
import yaml
from app.modules.notifications.service import (
    ALLOWED_TEMPLATE_DATA,
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
            assert entry[language]["subject"].strip()
            assert entry[language]["body"].strip()


def test_template_copy_uses_only_allowed_placeholders() -> None:
    placeholders = re.compile(r"\{([a-z_]+)\}")
    for template_id, entry in _copy()["templates"].items():
        for language, text in entry.items():
            used = set(
                placeholders.findall(text["subject"])
                + placeholders.findall(text.get("subject_detail") or "")
                + placeholders.findall(text["body"])
            )
            assert used <= ALLOWED_TEMPLATE_DATA, f"{template_id}/{language}: {used}"


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
