"""Calendar integrations for confirmed bookings.

Two outputs, both consumed by ``confirm_booking``:

1. ``build_google_calendar_url`` — a deep link to Google Calendar's
   "create event" form, pre-filled with event details. Zero auth, pure
   URL construction. Returned in the booking response so the user can
   one-click add the event to their own calendar.
2. ``build_ics_text`` — a UTF-8 iCalendar (RFC 5545) text blob with one
   ``VEVENT`` per unique event. Pure function, no I/O. Used as a Resend
   email attachment in commit 3/3 so any calendar app (Google, Apple,
   Outlook) can import the booking.

The full Google Calendar API (with OAuth) is deferred to a later phase;
these two surfaces are enough for a friction-free "add to calendar" UX
without the OAuth complexity.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ics import Calendar, Event

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


@dataclass(frozen=True)
class ICSEventInput:
    """One event's worth of data, ready to be rendered as a VEVENT.

    Kept deliberately decoupled from Cart / event-details models so the
    builder is a pure render step the booking layer can call after it
    has done its lookups. ``uid`` should be globally unique and stable
    (we use ``"<booking_id>:<event_id>@events-mcp"``) so a calendar app
    treats re-imports as updates, not duplicates.
    """

    uid: str
    title: str
    start_date: str | None
    start_time: str | None
    timezone: str | None
    location: str | None = None
    description: str | None = None


def build_ics_text(events: Iterable[ICSEventInput]) -> str:
    """Render an iCalendar (.ics) text blob with one VEVENT per input.

    - Events without ``start_date`` are skipped (cannot be represented).
    - Timed events: ``start_date`` + ``start_time`` interpreted in the
      given IANA timezone (falls back to UTC if missing or invalid).
      End is start + ``DEFAULT_DURATION_HOURS``, matching the Google
      Calendar deep link.
    - All-day events: ``start_date`` only, rendered as ``VALUE=DATE``.

    The output is RFC 5545 iCalendar text — directly usable as the body
    of a ``.ics`` email attachment with MIME type ``text/calendar``.
    """
    cal = Calendar()
    for ev in events:
        if not ev.start_date:
            continue

        e = Event()
        e.name = ev.title
        e.uid = ev.uid

        if ev.start_time:
            tz = _resolve_timezone(ev.timezone)
            start = datetime.strptime(
                f"{ev.start_date} {ev.start_time}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=tz)
            e.begin = start
            e.end = start + timedelta(hours=DEFAULT_DURATION_HOURS)
        else:
            e.begin = ev.start_date
            e.make_all_day()

        if ev.location:
            e.location = ev.location
        if ev.description:
            e.description = ev.description

        cal.events.add(e)

    return cal.serialize()


def _resolve_timezone(name: str | None) -> ZoneInfo:
    """Return ZoneInfo(name), or UTC if name is missing/unknown.

    Ticketmaster occasionally returns timezone strings the host system
    can't resolve (e.g. unusual venues). UTC is a safe fallback — the
    calendar invite stays valid; only the wall-clock display shifts.
    """
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")
