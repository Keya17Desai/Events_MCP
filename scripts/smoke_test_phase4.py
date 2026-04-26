"""Smoke test: full Phase 4 flow — favorites, preferences, recommendations.

1. Search New York events to grab a real event_id.
2. save_favorite that id.
3. save_favorite the same id again (idempotency).
4. list_favorites — should show the one event.
5. set_preferences with city='Mumbai', genres=['music'], email='you@example.com'.
6. get_preferences — should reflect what we set; email value never logged.
7. get_recommendations — uses preferences as filters, returns events.
8. remove_favorite — should drop the count to 0.

The .env-controlled DB lives at data/db.json — `cat` it after this run
to see exactly what got persisted. Re-running this test is safe: step 8
removes the favorite each time.

Run with:
    uv run python scripts/smoke_test_phase4.py
"""
from __future__ import annotations

import asyncio

from events_mcp.logging import configure_logging
from events_mcp.tools.discovery import search_events
from events_mcp.tools.favorites import (
    get_preferences,
    get_recommendations,
    list_favorites,
    remove_favorite,
    save_favorite,
    set_preferences,
)


def _section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


async def main() -> None:
    configure_logging()

    _section("0. Find a real event id to work with")
    search = await search_events(city="New York", size=1, sort="date,asc")
    if not search.events:
        print("No events returned — can't run the rest of the test.")
        return
    event = search.events[0]
    print(f"Using event: {event.name} ({event.id})")

    _section("1. save_favorite (first call — should write)")
    fav = await save_favorite(event_id=event.id)
    print(f"Saved: {fav.name} at {fav.venue_name}, saved_at={fav.saved_at}")

    _section("2. save_favorite again (idempotent — should NOT write)")
    fav_again = await save_favorite(event_id=event.id)
    assert fav.saved_at == fav_again.saved_at, "idempotency broken!"
    print("OK: same saved_at on second call, no duplicate row")

    _section("3. list_favorites")
    listed = list_favorites()
    print(f"Count: {listed.count}")
    for f in listed.favorites:
        print(f"  - {f.name} ({f.id})")

    _section("4. set_preferences (email is set but never appears in logs)")
    prefs = set_preferences(
        email="keya@example.com",
        preferred_city="Mumbai",
        preferred_genres=["music"],
        currency="INR",
    )
    print(f"Set: city={prefs.preferred_city}, genres={prefs.preferred_genres}, currency={prefs.currency}")
    print("(email value NOT printed here either)")

    _section("5. get_preferences — read back")
    got = get_preferences()
    print(f"city={got.preferred_city}, genres={got.preferred_genres}, currency={got.currency}")
    print(f"email is set: {got.email is not None}")

    _section("6. get_recommendations using those preferences")
    recs = await get_recommendations(size=3)
    print(f"Based on: {recs.based_on}")
    print(f"Returned {len(recs.events)} events:")
    for e in recs.events:
        print(f"  - {e.start_date}  {e.name[:50]}  ({e.city})")

    _section("7. remove_favorite — clean up so re-runs work")
    rm = remove_favorite(event_id=event.id)
    print(f"Removed: {rm.removed}, remaining: {rm.remaining}")


if __name__ == "__main__":
    asyncio.run(main())
