"""Google Calendar deep-link builder.

We build a URL for Google Calendar's "create event" form. The user clicks
it, Google opens the form pre-filled with the event details, and they
save it onto their own calendar. Zero auth, zero API call — pure URL
construction.

The full Google Calendar API (with OAuth) is deferred to a later phase;
this is enough for a one-click "add to calendar" experience.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode

GOOGLE_CALENDAR_BASE = "https://calendar.google.com/calendar/r/eventedit"

DEFAULT_DURATION_HOURS = 3


def build_google_calendar_url(
    *,
    title: str,
    start_date: str | None,
    start_time: str | None,
    timezone: str | None,
    location: str | None = None,
    details: str | None = None,
    duration_hours: int = DEFAULT_DURATION_HOURS,
) -> str | None:
    """Return a Google Calendar 'add event' deep link, or None if no date.

    - With both start_date and start_time → timed event, end = start +
      duration_hours. Pass `ctz` so Google interprets the local time
      correctly without us doing UTC math.
    - With start_date only → all-day event (Google's YYYYMMDD/YYYYMMDD
      shape). end is the next day, which is how Google represents a
      single-day all-day event.
    - With no start_date → return None; the caller should skip this event.
    """
    if not start_date:
        return None

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")

    if start_time:
        h, m, s = (int(x) for x in start_time.split(":"))
        start_dt = start_dt.replace(hour=h, minute=m, second=s)
        end_dt = start_dt + timedelta(hours=duration_hours)
        dates = f"{start_dt:%Y%m%dT%H%M%S}/{end_dt:%Y%m%dT%H%M%S}"
    else:
        end_dt = start_dt + timedelta(days=1)
        dates = f"{start_dt:%Y%m%d}/{end_dt:%Y%m%d}"

    params: dict[str, str] = {"text": title, "dates": dates}
    if start_time and timezone:
        params["ctz"] = timezone
    if location:
        params["location"] = location
    if details:
        params["details"] = details

    return f"{GOOGLE_CALENDAR_BASE}?{urlencode(params)}"
