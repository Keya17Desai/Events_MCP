"""MCP Prompts for event discovery.

Prompts are server-defined templates the user invokes via slash commands
in the AI client (e.g. /event_night_plan). Each function returns a string
of prompt text — the LLM then executes that text, calling our tools as
it goes.

The user typing the slash command fills in the function arguments via the
client UI; the server doesn't see them until the prompt is invoked.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field


def event_night_plan(
    city: Annotated[
        str,
        Field(description="City name, e.g. 'Mumbai'", min_length=1, strict=True),
    ],
    date: Annotated[
        str,
        Field(
            description="Date in YYYY-MM-DD",
            min_length=10,
            max_length=10,
            strict=True,
        ),
    ],
    budget: Annotated[
        str,
        Field(
            description="Budget per ticket, e.g. '₹2000', '$50', 'any'",
            strict=True,
        ),
    ] = "any",
) -> str:
    """Plan an evening of events in a city on a specific date."""
    return (
        f"Plan an evening of events in {city} on {date}.\n"
        f"Budget per ticket: {budget}.\n\n"
        f'Use the search_events tool with city="{city}", '
        f'start_date_time="{date}T00:00:00Z", '
        f'end_date_time="{date}T23:59:59Z".\n\n'
        "Pick the 3 most interesting events from the results. If a specific "
        "budget number was given, filter to events within it. For each pick, list:\n"
        "- Event name\n"
        "- Venue\n"
        "- Start time\n"
        "- Price range (flag any that exceed the stated budget)\n"
        "- One-sentence pitch explaining why it's worth attending\n\n"
        "Format the response as a markdown itinerary ordered by start time. "
        "End with a one-paragraph summary tying the evening together."
    )


def genre_picks(
    genre: Annotated[
        str,
        Field(
            description="Music genre or sport, e.g. 'rock', 'basketball', 'comedy'",
            min_length=1,
            strict=True,
        ),
    ],
    city: Annotated[
        str,
        Field(description="City name", min_length=1, strict=True),
    ],
) -> str:
    """Curated picks for a genre fan in a specific city."""
    return (
        f"Find the best {genre} events in {city} for an enthusiastic fan.\n\n"
        f'Use search_events with city="{city}" and a keyword or classification '
        f'that matches "{genre}". Look across the next 60 days.\n\n'
        "Pick 5 standouts. Optimize for:\n"
        "- Variety (different artists/venues, no duplicates)\n"
        "- Range of dates (don't cluster everything in one week)\n"
        "- Price range diversity (some splurge, some accessible)\n\n"
        "Return as a numbered list. For each:\n"
        "1. Event name\n"
        "2. Date and venue\n"
        "3. Price range\n"
        f"4. A one-line pitch explaining what makes this event special for a {genre} fan"
    )


def compare_events(
    event_id_a: Annotated[
        str,
        Field(
            description="First Ticketmaster event id (from search_events)",
            min_length=1,
            strict=True,
        ),
    ],
    event_id_b: Annotated[
        str,
        Field(
            description="Second Ticketmaster event id (from search_events)",
            min_length=1,
            strict=True,
        ),
    ],
) -> str:
    """Side-by-side comparison of two events with a recommendation."""
    return (
        f"Compare two events side by side: {event_id_a} vs {event_id_b}.\n\n"
        f'1. Use get_event_details with event_id="{event_id_a}".\n'
        f'2. Use get_event_details with event_id="{event_id_b}".\n\n'
        "Build a markdown comparison table:\n"
        "| Dimension | Event A | Event B |\n\n"
        "Cover these rows:\n"
        "- Name (and headliner, if a concert)\n"
        "- Date and start time\n"
        "- Venue (with city)\n"
        "- Price range\n"
        "- Genre / classification\n"
        "- Sales window (when tickets are on sale)\n\n"
        "After the table, give a 2-3 sentence recommendation: which one to "
        "pick and why, based on what's distinctive about each. Be honest "
        "about tradeoffs — don't sell both equally."
    )


def surprise_me(
    city: Annotated[
        str,
        Field(description="City name", min_length=1, strict=True),
    ],
) -> str:
    """Pick one off-the-beaten-path event in the city and pitch it."""
    return (
        f"Pick ONE event in {city} I might not have considered, and pitch it to me.\n\n"
        f'Use search_events with city="{city}" and size=20. Look through the '
        "results and skip the obvious headliners. Look for:\n"
        "- Off-genre or unexpected combinations\n"
        "- Smaller venues with character\n"
        "- Lesser-known artists, teams, or productions\n"
        "- Quirky themes (tribute acts, immersive theater, niche comedy)\n\n"
        "Return:\n"
        "- Event name + venue + date + price (one line)\n"
        "- 2-3 sentence pitch explaining why it could be memorable\n"
        "- An honest caveat: small venue, niche genre, late start, etc.\n\n"
        "Do NOT pick something just because it's the cheapest or earliest. "
        "Pick something genuinely interesting."
    )
