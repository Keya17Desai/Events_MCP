"""Pydantic models for venue data."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VenueSummary(BaseModel):
    """A single venue as exposed to the LLM."""

    id: str = Field(..., description="Ticketmaster venue id")
    name: str
    url: str | None = None

    city: str | None = None
    state: str | None = None
    country_code: str | None = None
    address: str | None = None
    postal_code: str | None = None
    timezone: str | None = None

    @classmethod
    def from_api_venue(cls, raw: dict[str, Any]) -> VenueSummary:
        return cls(
            id=raw["id"],
            name=raw.get("name", ""),
            url=raw.get("url"),
            city=(raw.get("city") or {}).get("name"),
            state=(raw.get("state") or {}).get("name"),
            country_code=(raw.get("country") or {}).get("countryCode"),
            address=(raw.get("address") or {}).get("line1"),
            postal_code=raw.get("postalCode"),
            timezone=raw.get("timezone"),
        )


class SearchVenuesResult(BaseModel):
    """Top-level response for the search_venues tool."""

    venues: list[VenueSummary]
    total_results: int = Field(..., description="Total matching venues across all pages")
    page: int
    page_size: int
