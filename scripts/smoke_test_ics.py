"""Smoke test: Phase 5.5 commit 2/3 — .ics builder.

Pure-function test, no I/O. Exercises the three branches of
``build_ics_text``:

1. Timed event with a real IANA timezone.
2. All-day event (no start_time).
3. Missing start_date — silently skipped.

Plus an unknown-timezone fallback to confirm we don't blow up on
Ticketmaster's occasional weird tz strings.

Run with:
    uv run python scripts/smoke_test_ics.py
"""
from __future__ import annotations

from events_mcp.notifications.calendar import (
    DEFAULT_DURATION_HOURS,
    ICSEventInput,
    build_ics_text,
)


def _section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def main() -> None:
    _section("1. Timed + all-day + skipped — three events in one calendar")
    timed = ICSEventInput(
        uid="booking-abc:event-1@events-mcp",
        title="Coldplay — Music of the Spheres",
        start_date="2026-05-15",
        start_time="19:30:00",
        timezone="America/New_York",
        location="Madison Square Garden, New York",
        description="Booking abc — 2 tickets via Events MCP.",
    )
    all_day = ICSEventInput(
        uid="booking-abc:event-2@events-mcp",
        title="Met Museum — Surrealism Exhibit",
        start_date="2026-05-16",
        start_time=None,
        timezone=None,
        location="The Met, New York",
    )
    skipped = ICSEventInput(
        uid="booking-abc:event-3@events-mcp",
        title="Date TBD Event",
        start_date=None,
        start_time=None,
        timezone=None,
    )

    text = build_ics_text([timed, all_day, skipped])
    print(text)

    assert text.startswith("BEGIN:VCALENDAR"), "missing VCALENDAR opener"
    assert text.rstrip().endswith("END:VCALENDAR"), "missing VCALENDAR closer"
    assert text.count("BEGIN:VEVENT") == 2, "expected 2 VEVENTs (skipped one)"
    assert text.count("END:VEVENT") == 2

    assert "SUMMARY:Coldplay" in text
    assert "SUMMARY:Met Museum" in text
    assert "Date TBD" not in text, "skipped event should not appear"

    # Timed event — ics renders tz-aware datetimes in UTC. NY is UTC-4
    # in May (EDT), so 19:30 EDT → 23:30 UTC; end is 3h later = 02:30 UTC
    # the next day.
    assert "DTSTART:20260515T233000Z" in text, "expected UTC-converted start"
    assert "DTEND:20260516T023000Z" in text, (
        f"expected start + {DEFAULT_DURATION_HOURS}h end"
    )

    # All-day event — VALUE=DATE form, no time component.
    assert "DTSTART;VALUE=DATE:20260516" in text, "expected all-day form"

    # Stable UIDs survive the round trip — important for calendar dedup.
    assert "UID:booking-abc:event-1@events-mcp" in text
    assert "UID:booking-abc:event-2@events-mcp" in text

    print("\nOK: 2 VEVENTs rendered, 1 skipped, UTC + all-day forms correct")

    _section("2. Empty input → valid empty calendar")
    empty = build_ics_text([])
    assert "BEGIN:VCALENDAR" in empty
    assert "END:VCALENDAR" in empty
    assert "BEGIN:VEVENT" not in empty
    print("OK: empty calendar renders without errors")

    _section("3. Unknown timezone falls back to UTC, no crash")
    bogus_tz = ICSEventInput(
        uid="bogus@events-mcp",
        title="Festival of Bogus Timezones",
        start_date="2026-06-01",
        start_time="20:00:00",
        timezone="Not/A_Real_Zone",
    )
    text2 = build_ics_text([bogus_tz])
    # 20:00 UTC stays 20:00 UTC — confirms fallback kicked in.
    assert "DTSTART:20260601T200000Z" in text2, (
        "expected UTC fallback when tz is unresolvable"
    )
    print("OK: unresolvable tz fell back to UTC")


if __name__ == "__main__":
    main()
