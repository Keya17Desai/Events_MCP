"""Pydantic models for attraction data (artists, teams, performers)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AttractionSummary(BaseModel):
    """A single attraction (artist, team, or performer)."""

    id: str = Field(..., description="Ticketmaster attraction id")
    name: str
    url: str | None = None
    segment: str | None = Field(None, description="Top-level category, e.g. 'Music', 'Sports'")
    genre: str | None = Field(None, description="Sub-category, e.g. 'Rock', 'Basketball'")
    image_url: str | None = None

    @classmethod
    def from_api_attraction(cls, raw: dict[str, Any]) -> AttractionSummary:
        classifications = raw.get("classifications") or []
        classification = classifications[0] if classifications else {}

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
            segment=(classification.get("segment") or {}).get("name"),
            genre=(classification.get("genre") or {}).get("name"),
            image_url=image_url,
        )


class SearchAttractionsResult(BaseModel):
    """Top-level response for the search_attractions tool."""

    attractions: list[AttractionSummary]
    total_results: int = Field(..., description="Total matching attractions across all pages")
    page: int
    page_size: int
