"""Async HTTP client for the Ticketmaster Discovery API.

Wraps httpx.AsyncClient with auth injection and uniform error handling.
Use as an async context manager so the connection pool is closed cleanly:

    async with TicketmasterClient(api_key="...") as client:
        data = await client.search_events_raw(keyword="Coldplay")
"""
from __future__ import annotations

from typing import Any

import httpx

DISCOVERY_BASE_URL = "https://app.ticketmaster.com/discovery/v2/"
DEFAULT_TIMEOUT_SECONDS = 10.0


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

    async def __aexit__(self, *_exc: Any) -> None:
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
        merged_params = {"apikey": self._api_key, **(params or {})}
        try:
            response = await self._client.get(path, params=merged_params)
        except httpx.HTTPError as exc:
            raise TicketmasterAPIError(f"HTTP request failed: {exc}") from exc

        if response.is_error:
            raise TicketmasterAPIError(
                f"Ticketmaster API returned {response.status_code}: "
                f"{response.text[:200]}"
            )

        return response.json()

    async def search_events_raw(self, **params: Any) -> dict[str, Any]:
        """GET /events.json — search events. Returns raw JSON."""
        return await self._get("events.json", params=params)

    async def get_event_raw(self, event_id: str) -> dict[str, Any]:
        """GET /events/{id}.json — full details for one event."""
        return await self._get(f"events/{event_id}.json")

    async def search_venues_raw(self, **params: Any) -> dict[str, Any]:
        """GET /venues.json — search venues."""
        return await self._get("venues.json", params=params)

    async def search_attractions_raw(self, **params: Any) -> dict[str, Any]:
        """GET /attractions.json — search artists, teams, performers."""
        return await self._get("attractions.json", params=params)
