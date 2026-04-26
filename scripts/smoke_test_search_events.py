"""Smoke test: exercise the search_events tool function end-to-end.

Run with:
    uv run python scripts/smoke_test_search_events.py

Calls the search_events tool directly (not through MCP) so we can verify
the API client + Pydantic transform works before wiring it into Claude.
"""
from __future__ import annotations

import asyncio

from events_mcp.logging import configure_logging
from events_mcp.tools.discovery import search_events


async def main() -> None:
    configure_logging()
    result = await search_events(city="New York", size=3)
    print(f"Total matching: {result.total_results}, showing {len(result.events)}")
    for event in result.events:
        print(f"  - {event.name}")
        print(f"      venue: {event.venue_name}, {event.city}, {event.country_code}")
        print(f"      date:  {event.start_date} {event.start_time or ''}")
        print(f"      genre: {event.segment} / {event.genre}")
        if event.price_min is not None:
            print(
                f"      price: {event.price_min}-{event.price_max} "
                f"{event.price_currency}"
            )


if __name__ == "__main__":
    asyncio.run(main())
