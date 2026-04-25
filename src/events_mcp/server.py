from mcp.server.fastmcp import FastMCP
from pydantic import Field

mcp = FastMCP(
    "Events MCP",
    instructions="A server for discovering and booking live events. Currently in Phase 1 (hello world).",
)


@mcp.tool()
def hello(
    name: str = Field(..., description="Your name", min_length=1, max_length=100),
) -> str:
    """Say hello. Use this to verify the Events MCP server is running and connected."""
    return f"Hello, {name}! The Events MCP server is live and ready."


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
