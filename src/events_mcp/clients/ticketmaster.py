"""Async HTTP client for the Ticketmaster Discovery API.

Wraps httpx.AsyncClient with auth injection and uniform error handling.
Use as an async context manager so the connection pool is closed cleanly:

    async with TicketmasterClient(api_key="...") as client:
        data = await client.search_events_raw(keyword="Coldplay")
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from cachetools import TTLCache

from events_mcp.logging import get_logger

DISCOVERY_BASE_URL = "https://app.ticketmaster.com/discovery/v2/"
DEFAULT_TIMEOUT_SECONDS = 10.0

log = get_logger(__name__)

# Ticketmaster's documented "5 req/sec" actually enforces burst=1: requests
# must be evenly spaced, not crammed into the same 200ms. AsyncLimiter(1, 0.3)
# means "1 acquire per 300ms" — capacity 1 (no burst), sustained ~3.3/sec.
# Comfortably under 5/sec and avoids the 429 spike-arrest. Module-level so
# it's shared across every TicketmasterClient instance — putting it on the
# instance would let concurrent tool calls each get their own budget.
_RATE_LIMITER = AsyncLimiter(max_rate=1, time_period=0.3)

# Two TTL caches, both module-level for the same shared-singleton reason as
# the limiter. Searches change slowly (new events get added, prices shift) →
# 5 min. Single-event details change even less → 15 min.
_SEARCH_CACHE: TTLCache[tuple[Any, ...], dict[str, Any]] = TTLCache(
    maxsize=512, ttl=300
)
_DETAIL_CACHE: TTLCache[tuple[Any, ...], dict[str, Any]] = TTLCache(
    maxsize=512, ttl=900
)


class TicketmasterAPIError(RuntimeError):
    """Raised when the Ticketmaster API returns an error or the request fails."""


class TicketmasterClient:
    """Thin async wrapper over the Ticketmaster Discovery API."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=DISCOVERY_BASE_URL,
            timeout=timeout,
        )

    async def __aenter__(self) -> TicketmasterClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._client.aclose()

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue an authenticated GET request and return parsed JSON."""
        user_params = params or {}
        merged_params = {"apikey": self._api_key, **user_params}
        start = time.perf_counter()
        try:
            async with _RATE_LIMITER:
                response = await self._client.get(path, params=merged_params)
        except httpx.HTTPError as exc:
            duration_ms = round((time.perf_counter() - start) * 1000)
            log.error(
                "ticketmaster_request_failed",
                path=path,
                params=user_params,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise TicketmasterAPIError(f"HTTP request failed: {exc}") from exc

        duration_ms = round((time.perf_counter() - start) * 1000)
        if response.is_error:
            log.warning(
                "ticketmaster_request_error",
                path=path,
                params=user_params,
                status=response.status_code,
                duration_ms=duration_ms,
            )
            raise TicketmasterAPIError(
                f"Ticketmaster API returned {response.status_code}: "
                f"{response.text[:200]}"
            )

        log.info(
            "ticketmaster_request",
            path=path,
            params=user_params,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response.json()

    async def _cached_get(
        self,
        cache: TTLCache[tuple[Any, ...], dict[str, Any]],
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET with a TTL-cache lookup in front. Cache key excludes the API key."""
        user_params = params or {}
        key = (path, tuple(sorted(user_params.items())))
        if key in cache:
            log.info("cache_hit", path=path, params=user_params)
            return cache[key]
        log.info("cache_miss", path=path, params=user_params)
        data = await self._get(path, params=user_params)
        cache[key] = data
        return data

    async def search_events_raw(self, **params: Any) -> dict[str, Any]:
        """GET /events.json — search events. Returns raw JSON."""
        return await self._cached_get(_SEARCH_CACHE, "events.json", params=params)

    async def get_event_raw(self, event_id: str) -> dict[str, Any]:
        """GET /events/{id}.json — full details for one event."""
        return await self._cached_get(_DETAIL_CACHE, f"events/{event_id}.json")

    async def search_venues_raw(self, **params: Any) -> dict[str, Any]:
        """GET /venues.json — search venues."""
        return await self._cached_get(_SEARCH_CACHE, "venues.json", params=params)

    async def search_attractions_raw(self, **params: Any) -> dict[str, Any]:
        """GET /attractions.json — search artists, teams, performers."""
        return await self._cached_get(
            _SEARCH_CACHE, "attractions.json", params=params
        )
