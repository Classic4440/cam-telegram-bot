"""Parse durations and "when" phrases for reminders and countdowns."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_HORIZON = timedelta(days=366)

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "wk": 604800, "week": 604800, "weeks": 604800,
}
_DURATION_PART = r"\d+(?:\.\d+)?\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|wk|[smhdw])(?![a-z])"
_DURATION_ONE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-z]+)", re.I)
_DURATION_LEAD = re.compile(rf"^(?:in\s+)?((?:{_DURATION_PART}[\s,]*(?:and\s+)?)+)(.*)$", re.I | re.S)
_CLOCK_LEAD = re.compile(
    r"^(?:(?P<day>today|tomorrow|tonight)\s+)?(?P<at>at\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?\b\s*(?P<rest>.*)$",
    re.I | re.S,
)


class TimeParseError(ValueError):
    pass


def get_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise TimeParseError(f"Unknown timezone '{(name or '')[:40]}'. Use a name like Africa/Kampala or Europe/London.") from None


def parse_duration(text: str) -> float:
    """``"1h30m"`` / ``"2 days 3 hours"`` -> seconds."""
    total = 0.0
    found = False
    for number, unit in _DURATION_ONE.findall(text):
        factor = _UNIT_SECONDS.get(unit.lower())
        if factor is None:
            raise TimeParseError(f"Unknown time unit '{unit}'")
        total += float(number) * factor
        found = True
    if not found or total <= 0:
        raise TimeParseError("Couldn't read a duration like 10m, 2h30m or 3 days")
    return total


def parse_reminder(text: str, tz_name: str | None = None, now: datetime | None = None) -> tuple[datetime, str]:
    """Return ``(due_utc, message)`` from phrases such as::

        10m stretch            in 2 hours call mum        1h30m deploy
        18:30 stand-up         tomorrow 9am gym           at 7pm dinner
    """
    text = text.strip()
    if not text:
        raise TimeParseError("Tell me when and what, e.g. /remind 20m drink water")
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    zone = get_zone(tz_name)

    match = _DURATION_LEAD.match(text)
    if match and match.group(2).strip():
        seconds = parse_duration(match.group(1))
        due = now_utc + timedelta(seconds=seconds)
        message = match.group(2).strip()
    else:
        clock = _CLOCK_LEAD.match(text)
        if not clock or not clock.group("rest").strip():
            raise TimeParseError("Try: /remind 20m drink water, /remind 18:30 stand-up, /remind tomorrow 9am gym")
        hour, minute = int(clock.group("h")), int(clock.group("m") or 0)
        ap = (clock.group("ap") or "").lower()
        if not (clock.group("m") or ap or clock.group("at") or clock.group("day")):
            raise TimeParseError("Add a unit (20m, 2h) or a clock time (18:30, 7pm, at 7)")
        if ap:
            if not 1 <= hour <= 12:
                raise TimeParseError("Hours with am/pm must be 1-12")
            hour = hour % 12 + (12 if ap == "pm" else 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise TimeParseError("That isn't a valid time of day")
        local_now = now_utc.astimezone(zone)
        day = (clock.group("day") or "").lower()
        target = datetime.combine(local_now.date(), time(hour, minute), tzinfo=zone)
        if day == "tomorrow":
            target += timedelta(days=1)
        elif target <= local_now and day != "today" and day != "tonight":
            target += timedelta(days=1)
        elif target <= local_now:
            raise TimeParseError("That time has already passed today")
        due = target.astimezone(timezone.utc)
        message = clock.group("rest").strip()

    if due - now_utc > MAX_HORIZON:
        raise TimeParseError("Reminders can be at most one year ahead")
    if due <= now_utc:
        raise TimeParseError("That time is in the past")
    return due, message[:500]


def format_delta(seconds: float) -> str:
    seconds = int(max(0, round(seconds)))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    for value, label in ((days, "d"), (hours, "h"), (minutes, "m"), (secs, "s")):
        if value:
            parts.append(f"{value}{label}")
    return " ".join(parts[:3]) or "0s"


def parse_date(text: str) -> datetime:
    """ISO-ish dates: 2026-12-25, 2026-12-25 18:30, 25/12/2026 (day first)."""
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise TimeParseError("Use a date like 2026-12-25 or 25/12/2026 (optionally followed by HH:MM)")
