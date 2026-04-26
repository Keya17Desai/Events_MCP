"""Pydantic models for favorites and preferences.

Favorite extends EventSummary with two extra fields (user_id, saved_at)
so a stored favorite has the same shape as a search result + metadata.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from events_mcp.models.events import EventSummary


class Favorite(EventSummary):
    """An event the user has saved. Snapshot of the event fields at save-time."""

    user_id: str = Field(..., description="Owner of this favorite")
    saved_at: str = Field(..., description="ISO 8601 timestamp of when saved")


class ListFavoritesResult(BaseModel):
    favorites: list[Favorite]
    count: int


class RemoveFavoriteResult(BaseModel):
    removed: bool = Field(..., description="True if a record was deleted")
    event_id: str
    remaining: int = Field(..., description="Favorites remaining after removal")


class Preferences(BaseModel):
    """User preferences. All fields optional — preferences are upserted."""

    user_id: str = Field(..., description="Owner of these preferences")
    email: str | None = Field(
        None,
        description="Email for booking confirmations (Phase 5.5). Never logged.",
    )
    preferred_city: str | None = Field(
        None, description="City the user usually attends events in"
    )
    preferred_genres: list[str] = Field(
        default_factory=list,
        description="Genres or sports the user is interested in",
    )
    currency: str | None = Field(
        None,
        description="ISO currency code for displaying prices (e.g. 'INR', 'USD')",
    )


class RecommendationsResult(BaseModel):
    """Output of get_recommendations — events plus the filters that produced them."""

    events: list[EventSummary]
    based_on: dict[str, str | list[str] | None] = Field(
        ...,
        description=(
            "Filters that were used. Empty if no preferences are set — "
            "in which case events will also be empty."
        ),
    )
