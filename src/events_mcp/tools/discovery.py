"""Discovery tools — search and fetch live events from Ticketmaster."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from events_mcp.clients.ticketmaster import TicketmasterClient
from events_mcp.config import get_settings
from events_mcp.models.attractions import AttractionSummary, SearchAttractionsResult
from events_mcp.models.events import EventDetail, EventSummary, SearchEventsResult
from events_mcp.models.venues import SearchVenuesResult, VenueSummary


async def search_events(
    keyword: Annotated[
        str | None,
        Field(description="Free-text search across event name, artist, team, etc."),
    ] = None,
    city: Annotated[
        str | None,
        Field(description="City name, e.g. 'Mumbai', 'New York', 'London'"),
    ] = None,
    country_code: Annotated[
        str | None,
        Field(
            description="ISO country code (uppercase), e.g. 'US', 'IN', 'GB'",
            min_length=2,
            max_length=2,
        ),
    ] = None,
    classification: Annotated[
        str | None,
        Field(description="Top-level category: 'music', 'sports', 'arts', or 'family'"),
    ] = None,
    start_date_time: Annotated[
        str | None,
        Field(description="Earliest event start, ISO 8601 (e.g. '2026-04-25T00:00:00Z')"),
    ] = None,
    end_date_time: Annotated[
        str | None,
        Field(description="Latest event start, ISO 8601 (e.g. '2026-05-01T00:00:00Z')"),
    ] = None,
    size: Annotated[
        int,
        Field(description="Number of results per page (1-50)", ge=1, le=50),
    ] = 10,
    page: Annotated[
        int,
        Field(description="Zero-indexed page number for pagination", ge=0),
    ] = 0,
) -> SearchEventsResult:
    """Search live events on Ticketmaster.

    All filters are optional but at least one (city, country_code, keyword,
    or classification) is strongly recommended — unfiltered searches return
    arbitrary global results.
    """
    api_params: dict[str, Any] = {"size": size, "page": page}
    if keyword:
        api_params["keyword"] = keyword
    if city:
        api_params["city"] = city
    if country_code:
        api_params["countryCode"] = country_code
    if classification:
        api_params["classificationName"] = classification
    if start_date_time:
        api_params["startDateTime"] = start_date_time
    if end_date_time:
        api_params["endDateTime"] = end_date_time

    settings = get_settings()
    async with TicketmasterClient(settings.ticketmaster_api_key) as client:
        data = await client.search_events_raw(**api_params)

    raw_events = (data.get("_embedded") or {}).get("events") or []
    events = [EventSummary.from_api_event(e) for e in raw_events]

    page_info = data.get("page") or {}
    return SearchEventsResult(
        events=events,
        total_results=page_info.get("totalElements", len(events)),
        page=page_info.get("number", page),
        page_size=page_info.get("size", size),
    )


async def get_event_details(
    event_id: Annotated[
        str,
        Field(
            description="Ticketmaster event id (use the id from search_events results)",
            min_length=1,
        ),
    ],
) -> EventDetail:
    """Fetch full details for one event by id.

    Returns everything from search_events plus description, sales window,
    list of performers/teams, and a seatmap link if available.
    """
    settings = get_settings()
    async with TicketmasterClient(settings.ticketmaster_api_key) as client:
        data = await client.get_event_raw(event_id)
    return EventDetail.from_api_event(data)


async def search_venues(
    keyword: Annotated[
        str | None,
        Field(description="Free-text search across venue names"),
    ] = None,
    city: Annotated[
        str | None,
        Field(description="City name, e.g. 'Mumbai', 'Chicago'"),
    ] = None,
    country_code: Annotated[
        str | None,
        Field(
            description="ISO country code (uppercase), e.g. 'US', 'IN'",
            min_length=2,
            max_length=2,
        ),
    ] = None,
    size: Annotated[
        int,
        Field(description="Results per page (1-50)", ge=1, le=50),
    ] = 10,
    page: Annotated[
        int,
        Field(description="Zero-indexed page number", ge=0),
    ] = 0,
) -> SearchVenuesResult:
    """Search for venues (concert halls, stadiums, theaters).

    Useful when the user names a venue specifically ("events at Madison
    Square Garden") or wants to see what venues exist in a city.
    """
    api_params: dict[str, Any] = {"size": size, "page": page}
    if keyword:
        api_params["keyword"] = keyword
    if city:
        api_params["city"] = city
    if country_code:
        api_params["countryCode"] = country_code

    settings = get_settings()
    async with TicketmasterClient(settings.ticketmaster_api_key) as client:
        data = await client.search_venues_raw(**api_params)

    raw_venues = (data.get("_embedded") or {}).get("venues") or []
    venues = [VenueSummary.from_api_venue(v) for v in raw_venues]

    page_info = data.get("page") or {}
    return SearchVenuesResult(
        venues=venues,
        total_results=page_info.get("totalElements", len(venues)),
        page=page_info.get("number", page),
        page_size=page_info.get("size", size),
    )


async def search_attractions(
    keyword: Annotated[
        str | None,
        Field(description="Free-text search (artist, team, or performer name)"),
    ] = None,
    classification: Annotated[
        str | None,
        Field(description="Category: 'music', 'sports', 'arts', or 'family'"),
    ] = None,
    size: Annotated[
        int,
        Field(description="Results per page (1-50)", ge=1, le=50),
    ] = 10,
    page: Annotated[
        int,
        Field(description="Zero-indexed page number", ge=0),
    ] = 0,
) -> SearchAttractionsResult:
    """Search for attractions: artists, teams, or performers.

    Useful for resolving an artist/team name to a Ticketmaster id or for
    confirming spelling before searching events.
    """
    api_params: dict[str, Any] = {"size": size, "page": page}
    if keyword:
        api_params["keyword"] = keyword
    if classification:
        api_params["classificationName"] = classification

    settings = get_settings()
    async with TicketmasterClient(settings.ticketmaster_api_key) as client:
        data = await client.search_attractions_raw(**api_params)

    raw_attractions = (data.get("_embedded") or {}).get("attractions") or []
    attractions = [AttractionSummary.from_api_attraction(a) for a in raw_attractions]

    page_info = data.get("page") or {}
    return SearchAttractionsResult(
        attractions=attractions,
        total_results=page_info.get("totalElements", len(attractions)),
        page=page_info.get("number", page),
        page_size=page_info.get("size", size),
    )
