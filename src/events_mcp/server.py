from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from events_mcp.logging import configure_logging, get_logger
from events_mcp.prompts.discovery import (
    compare_events,
    event_night_plan,
    genre_picks,
    surprise_me,
)
from events_mcp.tools.discovery import (
    get_event_details,
    search_attractions,
    search_events,
    search_venues,
)
from events_mcp.tools.booking import (
    add_to_cart,
    confirm_booking,
    create_cart,
    generate_payment_link,
    get_cart,
    reserve_seats,
)
from events_mcp.tools.favorites import (
    get_preferences,
    get_recommendations,
    list_favorites,
    remove_favorite,
    save_favorite,
    set_preferences,
)

mcp = FastMCP(
    "Events MCP",
    instructions=(
        "A server for discovering live events (concerts, sports, theater, festivals). "
        "Use search_events to find events by city, keyword, category, or date."
    ),
)


@mcp.tool()
def hello(
    name: Annotated[
        str,
        Field(description="Your name", min_length=1, max_length=100, strict=True),
    ],
) -> str:
    """Say hello. Use this to verify the Events MCP server is running and connected."""
    return f"Hello, {name}! The Events MCP server is live and ready."


mcp.tool()(search_events)
mcp.tool()(get_event_details)
mcp.tool()(search_venues)
mcp.tool()(search_attractions)

mcp.tool()(save_favorite)
mcp.tool()(list_favorites)
mcp.tool()(remove_favorite)
mcp.tool()(set_preferences)
mcp.tool()(get_preferences)
mcp.tool()(get_recommendations)

mcp.tool()(create_cart)
mcp.tool()(add_to_cart)
mcp.tool()(get_cart)
mcp.tool()(reserve_seats)
mcp.tool()(generate_payment_link)
mcp.tool()(confirm_booking)


@mcp.resource("events://favorites")
def favorites_resource() -> str:
    """JSON list of all events the user has saved as favorites."""
    return list_favorites().model_dump_json(indent=2)


mcp.prompt()(event_night_plan)
mcp.prompt()(genre_picks)
mcp.prompt()(compare_events)
mcp.prompt()(surprise_me)


def main() -> None:
    configure_logging()
    log = get_logger(__name__)
    log.info("server_starting", transport="stdio")
    mcp.run()


if __name__ == "__main__":
    main()
