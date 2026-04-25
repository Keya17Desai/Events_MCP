"""Smoke test: verify the Ticketmaster client can hit the real API.

Run with:
    uv run python scripts/smoke_test_ticketmaster.py

Reads the API key from .env (via events_mcp.config), makes one live request,
and prints a summary. Intended as a quick sanity probe, not a unit test.
"""
from __future__ import annotations

import asyncio

from events_mcp.clients.ticketmaster import TicketmasterClient
from events_mcp.config import get_settings


async def main() -> None:
    settings = get_settings()
    async with TicketmasterClient(settings.ticketmaster_api_key) as client:
        data = await client.search_events_raw(countryCode="US", size=3)

    events = data.get("_embedded", {}).get("events", [])
    print(f"Got {len(events)} events from Ticketmaster.")
    for event in events:
        name = event.get("name", "?")
        date = event.get("dates", {}).get("start", {}).get("localDate", "?")
        print(f"  - {name}  ({date})")


if __name__ == "__main__":
    asyncio.run(main())
