"""Smoke test: verify the TTL cache is hit on repeat queries.

Calls search_events twice with identical args. The first call should miss
the cache and hit the network (~1-2s). The second should be a cache hit
(<10ms) — proving we're not double-spending API quota on duplicate queries.

Run with:
    uv run python scripts/smoke_test_cache.py
"""
from __future__ import annotations

import asyncio
import time

from events_mcp.logging import configure_logging
from events_mcp.tools.discovery import search_events


async def main() -> None:
    configure_logging()

    t1 = time.perf_counter()
    await search_events(city="Mumbai", size=3)
    elapsed1 = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    await search_events(city="Mumbai", size=3)
    elapsed2 = (time.perf_counter() - t2) * 1000

    print(f"\nFirst  call (network): {elapsed1:.0f}ms")
    print(f"Second call (cache):   {elapsed2:.0f}ms")
    print(f"Speedup: {elapsed1 / max(elapsed2, 0.01):.0f}x")


if __name__ == "__main__":
    asyncio.run(main())
