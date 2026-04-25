"""Smoke test all Phase 2 discovery tools end-to-end.

Run with:
    uv run python scripts/smoke_test_phase2_all.py

Exercises search_events, get_event_details, search_venues, and
search_attractions against the live Ticketmaster API.
"""
from __future__ import annotations

import asyncio

from events_mcp.tools.discovery import (
    get_event_details,
    search_attractions,
    search_events,
    search_venues,
)


async def main() -> None:
    print("=== search_events ===")
    events = await search_events(city="New York", size=2)
    print(f"  total: {events.total_results}, showing: {len(events.events)}")
    for e in events.events:
        print(f"  - [{e.id}] {e.name}")

    if events.events:
        first_id = events.events[0].id
        print(f"\n=== get_event_details (id={first_id}) ===")
        detail = await get_event_details(event_id=first_id)
        print(f"  name:       {detail.name}")
        print(f"  segment:    {detail.segment} / {detail.genre}")
        print(f"  sale start: {detail.sales_public_start}")
        print(f"  attractions:{detail.attractions}")
        print(f"  seatmap:    {detail.seatmap_url or '(none)'}")

    print("\n=== search_venues ===")
    venues = await search_venues(city="Chicago", size=3)
    print(f"  total: {venues.total_results}, showing: {len(venues.venues)}")
    for v in venues.venues:
        print(f"  - {v.name} ({v.city}, {v.country_code})")

    print("\n=== search_attractions ===")
    attractions = await search_attractions(keyword="Coldplay", size=3)
    print(f"  total: {attractions.total_results}, showing: {len(attractions.attractions)}")
    for a in attractions.attractions:
        print(f"  - {a.name} [{a.segment}/{a.genre}]")


if __name__ == "__main__":
    asyncio.run(main())
