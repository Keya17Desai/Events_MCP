"""Pydantic models for event data exposed by MCP tools.

We deliberately don't mirror Ticketmaster's full response shape. Only the
fields useful to the LLM are surfaced, in a flat structure. The transform
from raw API JSON lives here so tool code stays focused on orchestration.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EventSummary(BaseModel):
    """A single event as exposed to the LLM (search result form)."""

    id: str = Field(..., description="Ticketmaster event id, usable with get_event_details")
    name: str
    url: str | None = Field(None, description="Public Ticketmaster page for the event")

    start_date: str | None = Field(None, description="Local date (YYYY-MM-DD)")
    start_time: str | None = Field(None, description="Local time (HH:MM:SS)")
    timezone: str | None = None

    venue_name: str | None = None
    city: str | None = None
    country_code: str | None = None

    segment: str | None = Field(None, description="Top-level category, e.g. 'Music', 'Sports'")
    genre: str | None = Field(None, description="Sub-category, e.g. 'Rock', 'Basketball'")

    price_min: float | None = None
    price_max: float | None = None
    price_currency: str | None = None

    image_url: str | None = None

    @classmethod
    def from_api_event(cls, raw: dict[str, Any]) -> EventSummary:
        """Flatten one raw event dict from the Ticketmaster response."""
        dates = raw.get("dates") or {}
        start = dates.get("start") or {}

        venues = (raw.get("_embedded") or {}).get("venues") or []
        venue = venues[0] if venues else {}

        classifications = raw.get("classifications") or []
        classification = classifications[0] if classifications else {}

        price_ranges = raw.get("priceRanges") or []
        price = price_ranges[0] if price_ranges else {}

        images = raw.get("images") or []
        image_url: str | None = None
        for img in images:
            if img.get("ratio") == "16_9":
                image_url = img.get("url")
                break
        if image_url is None and images:
            image_url = images[0].get("url")

        return cls(
            id=raw["id"],
            name=raw.get("name", ""),
            url=raw.get("url"),
            start_date=start.get("localDate"),
            start_time=start.get("localTime"),
            timezone=dates.get("timezone"),
            venue_name=venue.get("name"),
            city=(venue.get("city") or {}).get("name"),
            country_code=(venue.get("country") or {}).get("countryCode"),
            segment=(classification.get("segment") or {}).get("name"),
            genre=(classification.get("genre") or {}).get("name"),
            price_min=price.get("min"),
            price_max=price.get("max"),
            price_currency=price.get("currency"),
            image_url=image_url,
        )


class SearchEventsResult(BaseModel):
    """Top-level response for the search_events tool."""

    events: list[EventSummary]
    total_results: int = Field(..., description="Total matching events across all pages")
    page: int
    page_size: int


class EventDetail(EventSummary):
    """Full event details — extends EventSummary with extra fields."""

    info: str | None = Field(None, description="Short info / description text")
    please_note: str | None = Field(None, description="Restrictions, accessibility notes")
    sales_public_start: str | None = Field(None, description="When tickets go on sale (ISO 8601)")
    sales_public_end: str | None = Field(None, description="When sale ends (ISO 8601)")
    attractions: list[str] = Field(default_factory=list, description="Performers / teams")
    seatmap_url: str | None = None

    @classmethod
    def from_api_event(cls, raw: dict[str, Any]) -> EventDetail:
        summary = EventSummary.from_api_event(raw)

        sales_public = ((raw.get("sales") or {}).get("public")) or {}
        attractions_raw = (raw.get("_embedded") or {}).get("attractions") or []
        seatmap = raw.get("seatmap") or {}

        return cls(
            **summary.model_dump(),
            info=raw.get("info"),
            please_note=raw.get("pleaseNote"),
            sales_public_start=sales_public.get("startDateTime"),
            sales_public_end=sales_public.get("endDateTime"),
            attractions=[a.get("name", "") for a in attractions_raw],
            seatmap_url=seatmap.get("staticUrl"),
        )
