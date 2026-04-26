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
