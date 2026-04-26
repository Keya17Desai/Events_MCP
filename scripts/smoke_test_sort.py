"""Smoke test: verify the sort param flows through to Ticketmaster.

Searches the same city twice with different sort orders and prints the
first event from each. If sort is wired correctly the two lists should
look meaningfully different.

Run with:
    uv run python scripts/smoke_test_sort.py
"""
from __future__ import annotations

import asyncio

from events_mcp.logging import configure_logging
from events_mcp.tools.discovery import search_events


async def main() -> None:
    configure_logging()

    print("\nsort='date,asc' — earliest events first:")
    asc = await search_events(city="New York", size=3, sort="date,asc")
    for e in asc.events:
        print(f"  {e.start_date}  {e.name[:55]}")

    print("\nsort='date,desc' — latest events first:")
    desc = await search_events(city="New York", size=3, sort="date,desc")
    for e in desc.events:
        print(f"  {e.start_date}  {e.name[:55]}")


if __name__ == "__main__":
    asyncio.run(main())
