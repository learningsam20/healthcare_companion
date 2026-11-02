"""Parse booking preferences from free-text chat (clinic-local Asia/Kolkata)."""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

CLINIC_TZ = ZoneInfo("Asia/Kolkata")

_DAY_WORDS = {
    "today": 0,
    "todays": 0,
    "tomorrow": 1,
    "tmrw": 1,
    "tmr": 1,
}

_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}


def parse_preferred_starts_at(
    text: str,
    *,
    now: dt.datetime | None = None,
) -> dt.datetime | None:
    """Best-effort preferred appointment instant from user text.

    Returns timezone-aware Asia/Kolkata datetime, or None when no usable time.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None
    clock = now.astimezone(CLINIC_TZ) if now else dt.datetime.now(CLINIC_TZ)

    day_offset: int | None = None
    for word, offset in _DAY_WORDS.items():
        if re.search(rf"\b{word}\b", raw):
            day_offset = offset
            break

    weekday_match = None
    for name, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", raw):
            weekday_match = weekday
            break

    time_match = re.search(
        r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b",
        raw,
        flags=re.I,
    )
    # Prefer explicit clock times; ignore bare small integers that are not times
    # when no am/pm and hour would be ambiguous without context — still accept 1-12/13-23.
    hour: int | None = None
    minute = 0
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        meridiem = (time_match.group(3) or "").replace(".", "").lower()
        if meridiem.startswith("p") and hour < 12:
            hour += 12
        elif meridiem.startswith("a") and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            hour = None

    if hour is None and day_offset is None and weekday_match is None:
        return None

    if hour is None:
        # Day mentioned without time — default to next clinic opening hint (09:00).
        hour, minute = 9, 0

    target_date = clock.date()
    if day_offset is not None:
        target_date = clock.date() + dt.timedelta(days=day_offset)
    elif weekday_match is not None:
        delta = (weekday_match - clock.weekday()) % 7
        if delta == 0 and (hour, minute) <= (clock.hour, clock.minute):
            delta = 7
        target_date = clock.date() + dt.timedelta(days=delta)
    else:
        # Time only — today if still ahead, else tomorrow.
        candidate = dt.datetime.combine(
            clock.date(), dt.time(hour, minute), tzinfo=CLINIC_TZ
        )
        if candidate <= clock + dt.timedelta(minutes=30):
            target_date = clock.date() + dt.timedelta(days=1)

    preferred = dt.datetime.combine(
        target_date, dt.time(hour, minute), tzinfo=CLINIC_TZ
    )
    # Snap to 30-minute clinic grid.
    snap_minute = 0 if preferred.minute < 15 else 30 if preferred.minute < 45 else 0
    if preferred.minute >= 45:
        preferred = preferred + dt.timedelta(hours=1)
    preferred = preferred.replace(minute=snap_minute, second=0, microsecond=0)
    return preferred


def rank_slots_near_preference(
    slots: list[dict],
    preferred: dt.datetime | None,
    *,
    limit: int = 6,
) -> list[dict]:
    """Sort open slots by closeness to preferred time (or chronological)."""

    def _as_dt(value: object) -> dt.datetime | None:
        if isinstance(value, dt.datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=CLINIC_TZ)
            return value.astimezone(CLINIC_TZ)
        if isinstance(value, str) and value.strip():
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=CLINIC_TZ)
            return parsed.astimezone(CLINIC_TZ)
        return None

    decorated: list[tuple[float, dt.datetime, dict]] = []
    for slot in slots:
        starts = _as_dt(slot.get("starts_at"))
        if starts is None:
            continue
        if preferred is None:
            score = starts.timestamp()
        else:
            score = abs((starts - preferred).total_seconds())
        decorated.append((score, starts, slot))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated[:limit]]


def format_slot_label(
    *,
    doctor_name: str,
    clinic_code: str,
    starts_at: dt.datetime,
    now: dt.datetime | None = None,
) -> str:
    clock = now.astimezone(CLINIC_TZ) if now else dt.datetime.now(CLINIC_TZ)
    local = starts_at.astimezone(CLINIC_TZ)
    if local.date() == clock.date():
        day = "Today"
    elif local.date() == clock.date() + dt.timedelta(days=1):
        day = "Tomorrow"
    else:
        day = local.strftime("%a %d %b")
    return f"{doctor_name} · {clinic_code} · {day} {local.strftime('%I:%M %p').lstrip('0')}"
