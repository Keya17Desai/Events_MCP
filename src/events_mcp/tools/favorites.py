"""Favorites, preferences, and recommendations tools.

All Phase 4 user-state tools live here. Storage is tinydb-backed (see
events_mcp.storage.db); every record is namespaced under a user_id
(hardcoded "default_user" for now).

Privacy:
- Email values are never logged. Logs note that email was set/changed
  but never include the value itself.
- All log lines reference user_id, never the email or other PII.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import Field
from tinydb import Query

from events_mcp.logging import get_logger
from events_mcp.models.events import EventSummary
from events_mcp.models.favorites import (
    Favorite,
    ListFavoritesResult,
    Preferences,
    RecommendationsResult,
    RemoveFavoriteResult,
)
from events_mcp.storage.db import (
    DEFAULT_USER_ID,
    favorites_table,
    preferences_table,
)
from events_mcp.tools.discovery import get_event_details, search_events

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Favorites ────────────────────────────────────────────────────────────


async def save_favorite(
    event_id: Annotated[
        str,
        Field(
            description="Ticketmaster event id (from search_events)",
            min_length=1,
            strict=True,
        ),
    ],
) -> Favorite:
    """Save an event as a favorite. Idempotent — saving the same event twice is a no-op.

    Snapshots the key event fields at save-time so listing favorites later
    is instant and doesn't burn API quota.
    """
    table = favorites_table()
    Fav = Query()

    existing = table.search(
        (Fav.user_id == DEFAULT_USER_ID) & (Fav.id == event_id)
    )
    if existing:
        log.info(
            "favorite_save_idempotent",
            user_id=DEFAULT_USER_ID,
            event_id=event_id,
        )
        return Favorite.model_validate(existing[0])

    detail = await get_event_details(event_id)
    summary = EventSummary.model_validate(detail.model_dump())

    favorite = Favorite(
        **summary.model_dump(),
        user_id=DEFAULT_USER_ID,
        saved_at=_now_iso(),
    )
    table.insert(favorite.model_dump())
    log.info("favorite_saved", user_id=DEFAULT_USER_ID, event_id=event_id)
    return favorite


def list_favorites() -> ListFavoritesResult:
    """List all events the user has saved as favorites, with event name, date, venue, and price."""
    table = favorites_table()
    Fav = Query()
    rows = table.search(Fav.user_id == DEFAULT_USER_ID)
    favorites = [Favorite.model_validate(row) for row in rows]
    log.info("favorites_listed", user_id=DEFAULT_USER_ID, count=len(favorites))
    return ListFavoritesResult(favorites=favorites, count=len(favorites))


def remove_favorite(
    event_id: Annotated[
        str,
        Field(
            description="Ticketmaster event id of the favorite to remove",
            min_length=1,
            strict=True,
        ),
    ],
) -> RemoveFavoriteResult:
    """Remove an event from favorites by id. No-op if not saved."""
    table = favorites_table()
    Fav = Query()
    removed_ids = table.remove(
        (Fav.user_id == DEFAULT_USER_ID) & (Fav.id == event_id)
    )
    remaining = len(table.search(Fav.user_id == DEFAULT_USER_ID))
    result = RemoveFavoriteResult(
        removed=bool(removed_ids),
        event_id=event_id,
        remaining=remaining,
    )
    log.info(
        "favorite_removed",
        user_id=DEFAULT_USER_ID,
        event_id=event_id,
        was_present=result.removed,
    )
    return result


# ─── Preferences ──────────────────────────────────────────────────────────


def set_preferences(
    email: Annotated[
        str | None,
        Field(
            description=(
                "Email for booking confirmations. Pass None to leave unchanged. "
                "Never logged."
            ),
            strict=True,
        ),
    ] = None,
    preferred_city: Annotated[
        str | None,
        Field(
            description="City you usually attend events in. Pass None to leave unchanged.",
            strict=True,
        ),
    ] = None,
    preferred_genres: Annotated[
        list[str] | None,
        Field(
            description=(
                "Genres or sports you're interested in. Pass [] to clear, "
                "None to leave unchanged."
            ),
            strict=True,
        ),
    ] = None,
    currency: Annotated[
        str | None,
        Field(
            description="ISO currency code, e.g. 'INR', 'USD'. Pass None to leave unchanged.",
            strict=True,
        ),
    ] = None,
) -> Preferences:
    """Upsert user preferences. Only fields you pass (non-None) are changed.

    Empty list / empty string clears the field; None means "leave it alone".
    """
    table = preferences_table()
    Pref = Query()
    existing = table.search(Pref.user_id == DEFAULT_USER_ID)
    current: dict[str, Any] = (
        dict(existing[0]) if existing else {"user_id": DEFAULT_USER_ID}
    )

    fields_changed: list[str] = []
    if email is not None:
        current["email"] = email
        fields_changed.append("email")
    if preferred_city is not None:
        current["preferred_city"] = preferred_city
        fields_changed.append("preferred_city")
    if preferred_genres is not None:
        current["preferred_genres"] = preferred_genres
        fields_changed.append("preferred_genres")
    if currency is not None:
        current["currency"] = currency
        fields_changed.append("currency")

    if existing:
        table.update(current, Pref.user_id == DEFAULT_USER_ID)
    else:
        table.insert(current)

    log.info(
        "preferences_updated",
        user_id=DEFAULT_USER_ID,
        fields_changed=fields_changed,
    )
    return Preferences.model_validate(current)


def get_preferences() -> Preferences:
    """Return the current user's preferences (city, genres, currency, email). All fields are None if never set via set_preferences."""
    table = preferences_table()
    Pref = Query()
    rows = table.search(Pref.user_id == DEFAULT_USER_ID)
    if rows:
        return Preferences.model_validate(rows[0])
    return Preferences(user_id=DEFAULT_USER_ID)


# ─── Recommendations ──────────────────────────────────────────────────────


async def get_recommendations(
    size: Annotated[
        int,
        Field(description="Max events to return (1-50)", ge=1, le=50, strict=True),
    ] = 10,
) -> RecommendationsResult:
    """Recommend events based on stored preferences (preferred_city, first preferred_genre).

    Returns events sorted by date (soonest first). If no preferences are set,
    returns an empty list and an empty `based_on` — call set_preferences first.
    """
    prefs = get_preferences()

    based_on: dict[str, str | list[str] | None] = {}
    if prefs.preferred_city:
        based_on["preferred_city"] = prefs.preferred_city
    if prefs.preferred_genres:
        based_on["preferred_genres"] = prefs.preferred_genres

    if not based_on:
        log.info("recommendations_skipped", user_id=DEFAULT_USER_ID, reason="no_preferences")
        return RecommendationsResult(events=[], based_on={})

    search_kwargs: dict[str, Any] = {"size": size, "sort": "date,asc"}
    if prefs.preferred_city:
        search_kwargs["city"] = prefs.preferred_city
    if prefs.preferred_genres:
        search_kwargs["classification"] = prefs.preferred_genres[0]

    result = await search_events(**search_kwargs)
    log.info(
        "recommendations_completed",
        user_id=DEFAULT_USER_ID,
        returned=len(result.events),
        based_on_keys=list(based_on.keys()),
    )
    return RecommendationsResult(events=result.events, based_on=based_on)
