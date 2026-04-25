# Events MCP — Concepts & Learnings

A living reference document. Updated as we progress through each phase.
Use this to recall *why* something works the way it does, not just *what* the code looks like.

---

## Phase 0 — Foundations

### What is MCP (Model Context Protocol)?

MCP is an open protocol (by Anthropic) that lets AI models like Claude talk to external tools and data sources in a standardized way. Think of it like USB-C — it's a universal connector between AI clients and servers, so any MCP-compatible client (Claude Desktop, Cursor, etc.) can plug into any MCP-compatible server without custom glue code.

**Without MCP:** Every AI app writes its own custom integration with every tool.
**With MCP:** Build a server once → any MCP client can use it.

---

### MCP Primitives (the three building blocks)

| Primitive | What it is | Analogy |
|---|---|---|
| **Tool** | A function the AI can call. Has a name, description, input schema, and returns a result. | Like a REST API endpoint |
| **Resource** | Read-only data the AI can access (files, DB rows, URLs). Identified by a URI. | Like a GET-only endpoint |
| **Prompt** | A reusable prompt template the AI can invoke. | Like a saved query / macro |

In this project we mainly use **Tools** (Phase 1-5) and one **Resource** (Phase 4 — favorites list).

---

### JSON-RPC 2.0

MCP messages are formatted as **JSON-RPC 2.0**. This is a lightweight protocol where:
- The client sends a **request** with a method name and params
- The server returns a **result** or an **error**
- Each message is a plain JSON object

Example — what actually flows over the wire when Claude calls our `hello` tool:

```json
// Client → Server (request)
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "hello",
    "arguments": { "name": "Keya" }
  }
}

// Server → Client (response)
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{ "type": "text", "text": "Hello, Keya! The Events MCP server is live." }]
  }
}
```

You never write this manually — FastMCP handles it. But knowing what's happening underneath helps debug issues.

---

### MCP Transports

A transport is the *channel* over which JSON-RPC messages travel. MCP supports two:

| Transport | How it works | When to use |
|---|---|---|
| **stdio** | Messages go over stdin/stdout of a subprocess. Claude Desktop launches your server as a child process. | Local development (Phase 1–5) |
| **Streamable HTTP** | Messages go over HTTP (POST + SSE for streaming). Server runs independently. | Deployment / public URLs (Phase 6) |

**Important in stdio mode:** stdout is owned by the protocol. Never use `print()` in your server — it will corrupt the JSON-RPC stream and break the connection. Use `stderr` or a logging library instead.

---

### The Tool-Calling Loop

This is the sequence of events every time Claude uses one of your tools:

```
1. User sends a message to Claude
2. Claude decides it needs a tool → sends a tools/call request to your server
3. Your server runs the function → returns the result
4. Claude reads the result → incorporates it into its response
5. Claude replies to the user
```

This loop can happen multiple times in one conversation (Claude might call `search_events`, read the result, then call `get_event_details` on one result — all before replying).

---

### Security Mindset (baked in from day one)

| Rule | Why |
|---|---|
| Validate every tool input with Pydantic | Tool inputs come from an LLM, not a human. The LLM might hallucinate unexpected values. |
| Never log secrets | API keys in logs = security incident. |
| Never `eval()` or `os.system()` with user data | Classic injection attack vector. |
| Sanitize external API responses | Event descriptions could contain prompt injection attempts. |
| Store secrets in `.env`, never in code | So they're never committed to git. |

---

## Phase 1 — Hello World MCP Server

### FastMCP

`FastMCP` is the high-level class in the official MCP Python SDK. It's to MCP what FastAPI is to HTTP — a decorator-based framework that handles the protocol for you.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My Server Name")

@mcp.tool()
def my_tool(param: str) -> str:
    return f"Result: {param}"

mcp.run()  # starts the server (stdio by default)
```

FastMCP automatically:
- Registers the function as an MCP tool
- Generates the JSON schema for inputs from type hints
- Runs Pydantic validation before calling your function
- Serializes your return value into a proper MCP response

---

### Pydantic `Field` for Input Validation — use `Annotated`

The modern Pydantic v2 + FastMCP idiom uses `typing.Annotated` to attach validation metadata to a parameter type without changing its default value:

```python
from typing import Annotated
from pydantic import Field

@mcp.tool()
def hello(
    name: Annotated[str, Field(description="Your name", min_length=1, max_length=100)],
) -> str:
    ...

@mcp.tool()
async def search_events(
    city: Annotated[str | None, Field(description="City name")] = None,
    size: Annotated[int, Field(description="Results per page", ge=1, le=50)] = 10,
) -> SearchEventsResult:
    ...
```

- `Annotated[T, Field(...)]` = the type is `T`; the `Field(...)` is metadata
- `description` = shown to the LLM in the tool schema (very important — this is how the AI knows what to pass)
- `min_length` / `max_length` / `ge` / `le` = enforced automatically before your function runs
- The default value (after `=`) is a *real* Python default

**Rule:** Every tool parameter in this project uses `Annotated[T, Field(...)]`. No bare `str` or `int` without metadata.

#### ⚠️ Gotcha: don't use `param: T = Field(default, ...)` directly

The older-looking pattern works inside FastMCP but **breaks when the function is called directly from Python** (e.g., a smoke test):

```python
# ❌ BAD — looks fine, but breaks direct calls
async def search_events(keyword: str | None = Field(None, description="...")):
    if keyword:  # ⚠️ keyword is a FieldInfo object, not None! Truthy → always enters branch
        ...
```

This is because `Field(None, ...)` returns a `FieldInfo` object. FastMCP knows how to interpret it as "default = None", but a regular Python call sees the `FieldInfo` itself as the parameter value. Result: `if keyword:` is always true, and you end up sending garbage values to your downstream API.

**Always use `Annotated[T, Field(...)] = real_default` instead.** We hit this exact bug on the first run of `search_events` — the smoke test sent `start_date_time=PydanticUndefined` to Ticketmaster and got a 400 error.

---

### Why the entry point is `events_mcp.server:main`

In `pyproject.toml`:
```toml
[project.scripts]
events-mcp = "events_mcp.server:main"
```

This tells `uv` to create a CLI command `events-mcp` that calls the `main()` function in `src/events_mcp/server.py`. This is how Claude Desktop launches our server — it runs `events-mcp` (or `uv run events-mcp`) as a subprocess and communicates via stdio.

---

### MCP Inspector

The MCP Inspector is a browser-based debugging tool (`@modelcontextprotocol/inspector`). It lets you:
- See all tools your server exposes
- Call them manually with test inputs
- See the raw JSON-RPC messages exchanged

Run it with:
```bash
uv run mcp dev src/events_mcp/server.py
# Opens at http://localhost:5173
```

Always test here first before connecting to Claude Desktop — faster feedback loop.

---

### Connecting to a Claude Client (stdio)

There are two ways to connect an MCP server, depending on your platform:

**Option A — Claude Desktop (macOS / Windows only).** Edit `~/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "events-mcp": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/project", "events-mcp"]
    }
  }
}
```
Restart the app to load.

**Option B — Claude Code CLI (Linux / all platforms).** Use the `claude mcp add` subcommand:
```bash
claude mcp add events-mcp -- uv run --directory "/absolute/path/to/project" events-mcp
```
The `--` separator is important — it tells the CLI parser that everything after it is the server's launch command (not flags meant for `claude mcp add` itself).

Useful related commands:
```bash
claude mcp list                    # see all registered MCP servers
claude mcp get events-mcp          # show details + connection status
claude mcp remove events-mcp -s local   # remove
```

**Important gotcha:** MCP servers are loaded at the *start* of a Claude session, not when added. After running `claude mcp add ...`, you must start a fresh `claude` session for the tools to appear. Inside that session, run `/mcp` to verify the server shows as connected and lists your tools.

This is the path we took on this Linux machine.

---

## Phase 2 — Ticketmaster Integration (upcoming)

### Concepts we'll learn:

| Concept | What it is |
|---|---|
| `httpx` | Async HTTP client (like `requests` but async-native). We use it to call the Ticketmaster API. |
| `async` / `await` | Python's concurrency model. Lets the server handle waiting for HTTP responses without blocking. |
| `python-dotenv` | Loads `.env` file into environment variables. Keeps secrets out of code. |
| Pydantic models | Full classes that validate and parse API response JSON into typed Python objects. |
| Async context managers | `async with httpx.AsyncClient() as client:` — ensures the HTTP connection is properly cleaned up. |

---

## Phase 3 — Robustness (upcoming)

| Concept | What it is |
|---|---|
| `cachetools` | In-memory cache with TTL (time-to-live). Avoids hitting the API for the same query twice in N minutes. |
| `aiolimiter` | Async rate limiter. Ensures we never exceed Ticketmaster's 5 req/sec limit. |
| `structlog` | Structured logging library. Logs as JSON (key=value pairs) instead of plain strings — easier to filter and parse. Writes to stderr, never stdout. |

---

## Phase 4 — User State & Persistence (upcoming)

| Concept | What it is |
|---|---|
| `tinydb` | Lightweight document database stored as a JSON file. No SQL, no server needed. Good for Phase 4; we'll graduate to SQLite later. |
| MCP Resources | A way to expose read-only data (like a favorites list) that Claude can read without calling a tool. Identified by a URI like `events://favorites`. |
| `user_id` namespacing | All stored data is keyed under a `user_id` (hardcoded to `"default_user"` for now) to make multi-user support easy to add later. |

---

## Phase 5 — Simulated Booking Flow (upcoming)

| Concept | What it is |
|---|---|
| State machine | A pattern where an object (the cart) moves through defined states: `created → items_added → reserved → paid → confirmed`. Invalid transitions are rejected. |
| Seat hold with expiry | A reservation that auto-expires after N minutes if not confirmed. Prevents indefinite holds. |
| Mock QR code | A generated string/image that represents a "ticket" — no real ticketing system involved. |

---

## Phase 6 — HTTP Transport & Deployment (upcoming)

| Concept | What it is |
|---|---|
| Streamable HTTP transport | MCP over HTTP instead of stdio. Client sends POST requests; server can stream responses via Server-Sent Events (SSE). |
| SSE (Server-Sent Events) | A protocol for the server to push multiple messages to the client over a single HTTP connection. Used for streaming tool results. |
| Deployment (Render/Railway) | Hosting the server on a public URL so anyone can use it, not just local Claude Desktop. |

---

## Key Commands Reference

```bash
# Initialize a new project
uv init project-name

# Add a dependency
uv add package-name

# Run a script
uv run script.py

# Run the MCP Inspector (live debug UI)
uv run mcp dev src/events_mcp/server.py

# Run the server directly
uv run events-mcp

# Run tests
uv run pytest

# Lint
uv run ruff check .

# Type check
uv run mypy src/
```

---

## Glossary

| Term | Meaning |
|---|---|
| MCP | Model Context Protocol — the open standard for AI-tool communication |
| FastMCP | High-level Python framework for building MCP servers |
| JSON-RPC | The message format MCP uses (JSON + remote procedure call pattern) |
| stdio | Standard input/output — the pipe between Claude Desktop and our server |
| Tool | An MCP-registered function the AI can call |
| Resource | Read-only data exposed to the AI via a URI |
| Pydantic | Python library for data validation using type annotations |
| `Field(...)` | Pydantic helper to add constraints and descriptions to model fields |
| `uv` | Fast Python package manager (replaces pip + virtualenv) |
| `.env` | A file of secret environment variables, never committed to git |
| TTL | Time-to-live — how long a cached value stays valid before expiring |
| SSE | Server-Sent Events — HTTP-based streaming protocol |
| State machine | A pattern where an object can only be in one of a fixed set of states |
