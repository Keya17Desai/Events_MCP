"""Smoke test: verify aiolimiter actually rate-limits outbound requests.

Fires 8 concurrent search_attractions calls. With AsyncLimiter(4, 1) the
first 4 should fire immediately and the remaining 4 should be spaced over
the next ~1 second.

Run with:
    uv run python scripts/smoke_test_rate_limit.py
"""
from __future__ import annotations

import asyncio
import time

from events_mcp.logging import configure_logging
from events_mcp.tools.discovery import search_attractions


async def main() -> None:
    configure_logging()

    start = time.perf_counter()
    results = await asyncio.gather(
        *[search_attractions(keyword=f"test{i}", size=1) for i in range(8)]
    )
    elapsed = time.perf_counter() - start

    print(f"\n8 concurrent calls completed in {elapsed:.2f}s")
    print(f"With 4 req/sec limit, expected at least ~1s. Got: {elapsed:.2f}s")
    print(f"Total returned: {sum(len(r.attractions) for r in results)} items")


if __name__ == "__main__":
    asyncio.run(main())
