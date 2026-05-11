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

## Phase 2 — Ticketmaster Integration

### `python-dotenv` + a cached `Settings` object

Secrets like API keys must never be hardcoded. The pattern we used:

1. `.env` file at project root holds `TICKETMASTER_API_KEY=...` (gitignored).
2. `.env.example` is committed as a template — same keys, no values.
3. `python-dotenv`'s `load_dotenv()` reads `.env` into `os.environ` at import time.
4. A Pydantic `Settings` model validates the loaded values.
5. `get_settings()` is wrapped in `@lru_cache(maxsize=1)` so validation runs once and the same instance is reused everywhere.

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    api_key = os.environ.get("TICKETMASTER_API_KEY")
    if api_key is None:
        raise RuntimeError("Missing TICKETMASTER_API_KEY...")
    return Settings(ticketmaster_api_key=api_key)
```

**Why a Pydantic `BaseModel` instead of just reading `os.environ` everywhere?** Validation in one place. If the key is missing or too short, the server fails fast with a clear error at startup, not deep inside an HTTP call. `model_config = {"frozen": True}` makes the settings immutable — you can't accidentally mutate config at runtime.

**Why `lru_cache`?** Cheap memoization for a function that takes no args. Saves re-parsing on every call and gives you a single canonical config object.

---

### `httpx.AsyncClient` as an async context manager

`httpx` is the async-native successor to `requests`. The key idea is the **connection pool**: rather than opening a new TCP connection per request, the client keeps connections alive and reuses them. That pool needs to be closed cleanly, which is why we use it as an async context manager:

```python
async with TicketmasterClient(api_key=...) as client:
    data = await client.search_events_raw(keyword="Coldplay")
# pool is closed here, even if an exception was raised inside
```

The `__aenter__` / `__aexit__` methods are the async equivalent of `__enter__` / `__exit__`. `async with` is to `with` what `await` is to a normal call — same shape, but it suspends instead of blocking.

Inside our wrapper:
- `httpx.AsyncClient(base_url=..., timeout=...)` creates the pool.
- `await self._client.aclose()` shuts it down.
- Auth is injected per-request by merging `{"apikey": self._api_key}` into the query params, so callers never touch the key.

**Why a wrapper class instead of using `httpx` directly in tools?** Three reasons: (1) auth is centralized — tools don't see the key, (2) error handling is uniform — one place to catch `httpx.HTTPError` and raise our own `TicketmasterAPIError`, (3) when Phase 3 adds caching and rate limiting, those layers slot into the wrapper without touching tool code.

---

### `async` / `await` in 60 seconds

Python coroutines are functions defined with `async def` that *don't run* when called — they return a coroutine object. You execute them by `await`-ing inside another coroutine, or by handing them to an event loop (`asyncio.run(...)`).

```python
async def fetch():
    response = await client.get(url)   # suspends here, lets other tasks run
    return response.json()
```

While `await client.get(...)` is waiting on the network, the event loop can service other coroutines. For an MCP server this matters because tools spend most of their time blocked on HTTP calls — `async` lets a single process handle multiple in-flight tool calls without threads.

FastMCP supports `async def` tool functions natively. Just declare them async and `await` your I/O.

---

### The `from_api_X` classmethod pattern

Ticketmaster responses are deeply nested and noisy — there are dozens of fields, half of them optional, and the structure is built around HAL `_embedded` links. We don't want the LLM seeing that shape. So every Pydantic model exposes a flat, LLM-friendly schema, and a classmethod handles the transformation:

```python
class EventSummary(BaseModel):
    id: str
    name: str
    venue_name: str | None = None
    city: str | None = None
    # ... flat fields only

    @classmethod
    def from_api_event(cls, raw: dict[str, Any]) -> EventSummary:
        venues = (raw.get("_embedded") or {}).get("venues") or []
        venue = venues[0] if venues else {}
        return cls(
            id=raw["id"],
            name=raw.get("name", ""),
            venue_name=venue.get("name"),
            city=(venue.get("city") or {}).get("name"),
            ...
        )
```

**Why a classmethod and not a free function or a Pydantic validator?** Classmethods keep the transform colocated with the model it produces — find the model, find how it's built. They also let subclasses override the transform: `EventDetail.from_api_event` calls `EventSummary.from_api_event` first and then layers on the extra fields. (See `EventDetail` for that pattern in action.)

**Why `(raw.get("_embedded") or {}).get(...)` everywhere?** Because Ticketmaster sometimes returns a key with value `None` instead of omitting it. `raw.get("_embedded", {})` returns `None` in that case, and chaining `.get()` on `None` crashes. The `or {}` idiom handles both "missing" and "explicitly null" in one shot.

---

### Tools transform raw → model, never expose raw

The convention established in Phase 2:

```
LLM → MCP tool → TicketmasterClient (returns raw JSON dict)
                 → Model.from_api_X(raw)         ← transform happens here
                 → return Model                  ← LLM sees only the clean shape
```

Tools are thin: validate inputs, call the client, run `from_api_X`, return. They never pass raw API JSON back to the LLM. This keeps the tool surface stable even if Ticketmaster changes their response shape — only the `from_api_X` methods need to update.

---

### One client per tool call (for now)

Each tool currently does:

```python
async with TicketmasterClient(api_key=...) as client:
    raw = await client.search_events_raw(...)
```

This means we open and close a connection pool per tool invocation. **That's wasteful** — pool reuse is the whole point of `httpx.AsyncClient`. We're doing it anyway for Phase 2 because (a) it's simple, (b) it makes each tool independently testable, and (c) the optimization is exactly what Phase 3 is for. In Phase 3 we'll lift the client to a long-lived module-level singleton with a shared cache and rate limiter sitting in front of it.

**Lesson:** premature optimization can make Phase 1 harder to reason about. Start dumb, optimize when you have the surrounding machinery (caching, rate limiting) that benefits from it.

---

### Pydantic gotcha that hit us live

We already flagged this in Phase 1, but it bit us for real in Phase 2 — worth re-noting because the failure mode is silent until the API rejects you:

```python
# ❌ BAD — works under FastMCP, breaks when called directly
async def search_events(keyword: str | None = Field(None, description="...")):
    if keyword:  # FieldInfo is truthy! Always enters this branch.
        params["keyword"] = keyword  # sends a FieldInfo object to httpx
```

`Field(None, ...)` returns a `FieldInfo` instance. FastMCP's tool dispatcher knows to interpret that as "default = None", but a direct Python call (like our `scripts/` smoke tests) sees `FieldInfo` as the actual argument value. The result was `keyword=PydanticUndefined` flying out to Ticketmaster, which 400'd.

**Always:** `param: Annotated[T, Field(...)] = real_default`. Defaults live to the right of `=`, descriptions live inside `Field(...)`. They never share a slot.

---

## Phase 3 — Robustness

### `structlog` — structured logging to stderr

Plain `logging.info("got 5 events for Mumbai")` is a wall of strings. structlog writes **events with key-value context** instead: `log.info("search_completed", city="Mumbai", count=5, cache_hit=False)`. Each call emits a record with timestamp, level, event name, and arbitrary fields you bind. That's grep-friendly and parser-friendly.

Two output modes, picked automatically based on `sys.stderr.isatty()`:
- **TTY (terminal):** `ConsoleRenderer` — colored, human-readable, key=value pairs on one line.
- **Non-TTY (Claude Desktop, redirect, pipe):** `JSONRenderer` — one JSON object per line. Trivial to ship to a log aggregator later.

```python
configure_logging()
log = get_logger(__name__)
log.info("ticketmaster_request", path="events.json", status=200, duration_ms=345)
```

**Critical rule for stdio MCP servers:** all log output goes to **stderr**. stdout is owned by the JSON-RPC protocol — anything written there will corrupt the message stream and break the connection. We enforce this with `PrintLoggerFactory(file=sys.stderr)`. There is no path in our codebase that writes to stdout.

**API key safety in logs:** the client logs `user_params` (the dict the tool passed in), not `merged_params` (which has `apikey` injected). The key never appears in any log line.

#### `configure_logging()` is idempotent

We guard with a module-level `_configured` flag so multiple calls are a no-op. Reason: tests and scripts can each call `configure_logging()` defensively without risk.

#### Convention for event names

Use `lower_snake_case` past-tense verbs for what happened: `cache_hit`, `cache_miss`, `ticketmaster_request`, `tool_completed`. Keep them short and consistent so log filters work cleanly.

---

### `aiolimiter` — async rate limiter

Ticketmaster allows 5 req/sec. We cap at 4/sec to leave headroom for retries and clock skew. `aiolimiter.AsyncLimiter(max_rate, time_period)` is an async context manager:

```python
async with _RATE_LIMITER:
    response = await self._client.get(...)
```

If acquiring the limiter would exceed the rate, the `async with` **suspends** the coroutine until a slot frees up. This composes with `httpx`'s async model — concurrent tool calls naturally queue at the limiter rather than blocking a thread.

#### Why module-level, not per-client

The limiter is a module-scoped singleton in `clients/ticketmaster.py`:

```python
_RATE_LIMITER = AsyncLimiter(max_rate=4, time_period=1)
```

We currently spin up a new `TicketmasterClient` per tool call. If the limiter lived on the instance, four simultaneous tool calls would each get their own 4/sec budget — 16/sec across the process, instantly violating the API quota. A module-level limiter is shared across every client instance, which is the only correct shape until Phase 4+ introduces a long-lived client.

#### Rate limiter ≠ throughput limiter

The limiter governs **acquire time**, not response time. Each individual request still takes ~1-2s of network latency. The limiter just delays when each one is allowed to start.

#### ⚠️ Gotcha: "5/sec" is not the real shape

We hit this live. Our first try was `AsyncLimiter(4, 1)` — capacity 4, leak rate 4/sec. That allows **4 requests to fire as a burst** at the start of every window. Ticketmaster responded with a 429:

```
Allowed rate : MessageRate{messagesPerPeriod=5,
                periodInMicroseconds=1000000,
                maxBurstMessageCount=1.0}
```

`maxBurstMessageCount=1.0` is the punchline. Ticketmaster's spike arrest enforces "5/sec with burst=1" — requests must be **evenly spaced at ~200ms intervals**, not packed into the same instant even if the per-second total stays under 5.

Fix: `AsyncLimiter(max_rate=1, time_period=0.3)` — capacity 1 (no burst possible), one slot every 300ms = ~3.3/sec sustained. Comfortably under 5/sec, no spike-arrest violations.

**Lesson:** when an API document says "N/sec", check whether the server enforces it as a sliding-window burst (allows packed bursts up to N) or a leaky-bucket smooth-rate (forces even spacing). They behave differently under load. Read the *response body* of a real 429 — Ticketmaster's was very explicit about its spike-arrest config, and that's what told us the real shape.

---

### `cachetools` — TTL cache for repeated queries

In-memory cache with time-based expiry. `TTLCache(maxsize=N, ttl=seconds)` is dict-like — entries auto-evict when their TTL elapses or when the cache hits its size cap.

We use **two caches**:
- `_SEARCH_CACHE` — `ttl=300` (5 min). Used by `search_events`, `search_venues`, `search_attractions`. Listings change slowly.
- `_DETAIL_CACHE` — `ttl=900` (15 min). Used by `get_event_details`. Single events change even less often.

Both are module-level for the same shared-singleton reason as the limiter.

#### Cache key construction

```python
key = (path, tuple(sorted(user_params.items())))
```

Two pieces matter here:
1. **Path is part of the key.** Without it, a `search_events` query with `{"size": 10}` would collide with a `search_venues` query with `{"size": 10}`.
2. **`sorted(items())` makes the dict order-independent.** Python dicts preserve insertion order, so `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` would otherwise produce different tuple keys for the same logical query.

The API key is **not** part of the cache key — we cache against `user_params`, not `merged_params`, so two different deployments using the same key wouldn't share cache entries (they'd each have their own process-local cache anyway, but the principle holds).

#### Cache layering with the rate limiter

Order in `_cached_get`: cache lookup → cache miss → `_get` (which acquires the rate limiter) → cache write. So **cache hits don't consume rate-limit budget**. This is the whole point: the cache is in front of the network, not in front of the limiter alone.

Smoke test: identical query twice — first call 1469ms (network), second 51ms (cache only, no network). 29× speedup, zero extra quota spent.

---

### Pydantic strict mode — reject type coercion

By default Pydantic *coerces* values: `"10"` → `10`, `"true"` → `True`. Convenient for HTTP forms, dangerous for LLM inputs — a hallucinated string would silently become a valid int.

Strict mode (`Field(strict=True, ...)`) rejects coercion outright:

```
Lenient with '10':       10 (coerced!)
Strict with '10':        rejected — Input should be a valid integer
```

We applied `strict=True` to **every** `Field(...)` on every tool input parameter. Range constraints (`ge`, `le`, `min_length`) still apply on top — they're orthogonal to strict mode.

#### Why only on tool inputs, not response models

Tool inputs are the LLM-facing boundary — they're the place where bad data enters the system. Response models (`EventSummary`, `VenueSummary`, etc.) are constructed from API JSON via explicit `from_api_X` classmethods; we already control the types coming out of those transforms, so strict mode wouldn't catch new bugs and might break on edge cases (e.g., the API returning a numeric string for a numeric field).

---

### What we did NOT do this phase

- **No retries.** A 500 from Ticketmaster currently surfaces as a tool error. Adding `tenacity`-style retry-with-backoff is a future-phase concern, not a robustness must-have for the learning project.
- **No long-lived shared client.** Each tool still does `async with TicketmasterClient(...)`. The cache and rate limiter are module-level so this remains correct. Lifting the client to a singleton becomes worthwhile when we add resources/state in Phase 4.
- **No log level config from env.** Hardcoded `INFO` for now. Trivial to add `LOG_LEVEL` env var later if needed.

---

## Phase 3.5 — MCP Surface Polish & Sorting

### MCP Prompts — server-side reusable templates

So far we'd only used **Tools** (functions the LLM picks). Prompts are a separate MCP primitive: **the user invokes them directly** in the AI client, usually as slash commands (`/event_night_plan`). The user fills in arguments via the client UI; the server returns prompt text; the LLM then executes that text — calling our tools as it goes.

Mental model:

```
User types /event_night_plan        ← user-driven, not LLM-driven
    → Client asks: "city? date? budget?"
    → User fills in
    → Server's event_night_plan(city, date, budget) returns a string
    → That string becomes the prompt the LLM sees
    → LLM runs the prompt, calling search_events along the way
```

Tools = **AI's verbs**. Prompts = **user's shortcuts**.

### How they look in code

```python
@mcp.prompt()
def event_night_plan(
    city: Annotated[str, Field(description="City name", strict=True)],
    date: Annotated[str, Field(description="Date (YYYY-MM-DD)", strict=True)],
    budget: Annotated[str, Field(strict=True)] = "any",
) -> str:
    return f"Plan an evening of events in {city} on {date}..."
```

Same `Annotated[T, Field(...)]` convention as tools. The function returns the prompt body; FastMCP handles the protocol-level message envelope.

#### Why prompts are *just text generators*

The function does **no I/O**. It does not call tools. It does not fetch data. It just renders prompt text. The actual work happens when the LLM executes the returned text and (in our case) calls `search_events`, `get_event_details`, etc.

This is a clean separation:
- **Prompt logic** = how to phrase the task to the LLM (text formatting only)
- **Tool logic** = the actual work (HTTP calls, data transforms)

Smoke test: `scripts/smoke_test_prompts.py` calls each prompt function with sample args and prints the rendered string. No network involved — prompts are pure functions.

### What we built (4 prompts)

| Slash command | Args | What the LLM does |
|---|---|---|
| `/event_night_plan` | city, date, budget? | Searches for events on that date, filters by budget, picks 3, formats as itinerary |
| `/genre_picks` | genre, city | Finds 5 events for a genre fan optimizing for variety, dates, price spread |
| `/compare_events` | event_id_a, event_id_b | Fetches both, builds a side-by-side comparison table, recommends |
| `/surprise_me` | city | Searches widely, deliberately skips obvious headliners, pitches one off-the-beaten-path event |

Each lives in `src/events_mcp/prompts/discovery.py` and is registered in `server.py` via `mcp.prompt()(...)`.

---

### `Literal[...]` types for enum-like inputs

Pydantic and `typing.Literal` are best friends for enumerated values. Where strings would be lenient, `Literal["a", "b", "c"]` rejects anything outside the listed values:

```python
EventSort = Literal[
    "name,asc", "name,desc",
    "date,asc", "date,desc",
    "relevance,asc", "relevance,desc",
    "random",
    "onSaleStartDate,asc", "onSaleStartDate,desc",
    "venueName,asc", "venueName,desc",
]

sort: Annotated[EventSort | None, Field(strict=True)] = None
```

Three benefits:
1. **The LLM's tool schema lists exactly the allowed values** — so it doesn't have to guess.
2. **Pydantic validates it** automatically — no manual `if sort not in {...}` check.
3. **Your IDE autocompletes them** — no typos.

#### Why three different sort literals

Ticketmaster's sort field accepts a different subset per endpoint: events allow `date`/`venueName`/`onSaleStartDate`, venues don't. We typed each search tool with its own `EventSort` / `VenueSort` / `AttractionSort` literal so the schema only advertises what actually works on that endpoint.

#### What we deliberately omitted: `distance,asc`

The API supports `distance,asc`, but only when paired with a `latlong` parameter. Calling it without latlong returns 400. Until we expose latlong (probably when we add geolocation in a later phase), we keep `distance,asc` out of the literal — the strict-typed schema can't list a broken option as valid.

### Cache + sort interaction (already correct)

Cache key is `(path, sorted(params.items()))`. The `sort` value is just another key in `params`, so `sort=date,asc` and `sort=date,desc` produce distinct cache entries automatically. We confirmed this in the smoke test — both calls logged `cache_miss`. No code change to caching needed.

---

## Phase 4 — User State & Persistence

### `tinydb` — a JSON-file document store

`tinydb` is a single-file document database. No server, no SQL, no schema migrations — every record is a Python dict, persisted as JSON. We open it once at module load:

```python
_db = TinyDB(DB_PATH, indent=2)

def favorites_table()   -> Table: return _db.table("favorites")
def preferences_table() -> Table: return _db.table("preferences")
def carts_table()       -> Table: return _db.table("carts")
```

A "table" in tinydb is just a named collection inside the same JSON file. We have three: `favorites`, `preferences`, and `carts` (Phase 5). All in `data/db.json`.

**Why this and not SQLite (yet)?** TinyDB's wire format is a JSON file you can `cat` and read. For a learning project where the data model is still moving, that's a feature. The cost is that there are no indexes — every query scans the table — but at our scale (a handful of records per user), scan cost is invisible. We'll graduate to SQLite when querying gets real.

#### Tinydb query DSL

```python
from tinydb import Query
Fav = Query()
table.search((Fav.user_id == DEFAULT_USER_ID) & (Fav.id == event_id))
```

`Query()` returns a builder object whose attribute access produces field-comparison expressions. `&` and `|` combine them. The expressions are evaluated against each row of the table in turn — no execution plan, no joins, just Python.

#### `EVENTS_MCP_DB_PATH` env override

`storage/db.py` checks `os.environ["EVENTS_MCP_DB_PATH"]` before falling back to the project default. Useful for tests that want a throwaway DB without touching the real one. The hook is in place; we haven't needed it yet because smoke tests just wipe their own slice of the table.

---

### `user_id` namespacing — forward-compat for auth

Every record we store includes a `user_id` field. All reads filter by it:

```python
table.search(Fav.user_id == DEFAULT_USER_ID)
```

Right now `DEFAULT_USER_ID = "default_user"` — a single hardcoded constant. The shape is what matters. When Phase 6.5 adds OIDC, the only change is "where does `user_id` come from at the call site" — the storage layer, models, and tools don't have to learn about auth. CLAUDE.md flagged this design choice up front; this phase is where it pays off.

Concrete consequences:
- Storage helpers like `favorites_table()` return the **whole table** — they don't pre-filter. The user filter is the caller's responsibility, because the caller is the one who knows whose data it is.
- We never write a "global" record without a `user_id`. Even `Preferences(user_id=DEFAULT_USER_ID)` for the empty/never-set case carries the namespace.

---

### Snapshot pattern (favorites edition)

Same idea as the cart's `event_name` / `unit_price` snapshotting in Phase 5: when `save_favorite` runs, it fetches the event details once and **freezes** the relevant fields onto the `Favorite` record. `list_favorites` later just reads that JSON — no API call, no quota burn, and the displayed fields can't drift.

The model itself just extends `EventSummary` with the extra metadata fields:

```python
class Favorite(EventSummary):
    user_id: str
    saved_at: str
```

Subclassing keeps the favorite shape identical to a search result + two metadata fields, so an LLM that's seen one knows how to read the other.

---

### Idempotent constructor pattern (again)

`save_favorite` checks for an existing record before writing — saving the same event twice returns the existing favorite, doesn't error, doesn't duplicate. Same shape as `create_cart` in Phase 5: **constructors that name a thing the user wants are idempotent on the existence of that thing.** It's how we avoid making the LLM keep state about whether it already called the tool.

---

### Sparse upsert — `None` means "leave alone", empty means "clear"

`set_preferences` takes every field as `Optional`, defaulting to `None`:

```python
def set_preferences(
    email: str | None = None,
    preferred_city: str | None = None,
    preferred_genres: list[str] | None = None,
    currency: str | None = None,
) -> Preferences: ...
```

Two semantics on the same `None` would be ambiguous, so we documented the convention: **`None` means "don't touch this field"; empty string / empty list means "clear this field".** The implementation only writes fields whose argument is non-None, so a single call can update one field without resetting the others.

This matches how a user actually interacts conversationally: "set my email to X" should not silently wipe their preferred genres. A schema where every call is a full replacement would force the LLM to re-pass values it never changed — a footgun.

---

### PII handling — log the event, never the value

`email` is the first piece of real PII we store. The convention we set:

```python
log.info(
    "preferences_updated",
    user_id=DEFAULT_USER_ID,
    fields_changed=fields_changed,  # ← list of field NAMES, not values
)
```

`fields_changed` is `["email", "currency"]`, never `{"email": "k@example.com"}`. The log line records *that* email was set, never *what* email. Same rule applies to anything PII-shaped going forward. We get this habit in now so adding more user data later doesn't require a logging audit. (CLAUDE.md "Forward-Compatible Design Choices, item 4".)

Field descriptions also flag the rule for the LLM, e.g. `"Email for booking confirmations. Never logged."` That description is part of the tool schema the LLM sees.

---

### MCP Resources — read-only data without a tool call

Tools are **AI-driven verbs** (the LLM calls them). Resources are **read-only nouns** the client can fetch directly via a URI:

```python
@mcp.resource("events://favorites")
def favorites_resource() -> str:
    """JSON list of all events the user has saved as favorites."""
    return list_favorites().model_dump_json(indent=2)
```

The URI scheme `events://` is ours — MCP lets servers define their own. A client can list resources, fetch `events://favorites`, and present the JSON to the user (or to the LLM) without invoking a tool round-trip.

**Why expose favorites this way as well as via `list_favorites`?** Same data, different consumption pattern. A tool call is a verb-shaped interaction ("get me my favorites"). A resource is a noun-shaped one ("here, look at this list of favorites") — useful when a UI wants to render the data, or when a prompt wants to attach it as context without forcing the LLM to make a call.

---

### Recommendations — preferences-driven search, transparent ranking

`get_recommendations` is **not** ML. It takes the user's stored `preferred_city` and the first item of `preferred_genres`, builds a filtered `search_events` call, and returns the result sorted by date:

```python
search_kwargs = {"size": size, "sort": "date,asc"}
if prefs.preferred_city:    search_kwargs["city"] = prefs.preferred_city
if prefs.preferred_genres:  search_kwargs["classification"] = prefs.preferred_genres[0]

result = await search_events(**search_kwargs)
return RecommendationsResult(events=result.events, based_on=based_on)
```

The result includes a `based_on` dict naming the filters that were applied. That's deliberate: the CLAUDE.md ethics rule says **"Recommendation transparency — if we sort/filter events, document the ranking logic."** The LLM can read `based_on` and tell the user *"these are based on your preferred city Mumbai and your interest in concerts"* — no black box.

If no preferences are set, we return an empty `events` list and an empty `based_on` instead of doing a generic fallback search. Better to say "I have no basis to recommend" than to invent one and pretend it's tailored.

---

## Phase 5 — Simulated Booking Flow

### The Cart finite state machine

A `Cart` moves through five states, in order:

```
CREATED → ITEMS_ADDED → RESERVED → PAID → CONFIRMED
```

States are `StrEnum` values (`CartState.CREATED`, etc.) on a single Pydantic `Cart` model — not a discriminated union. We picked the single-model shape because (a) the FSM is small, (b) most fields are shared across states, and (c) Pydantic discriminated unions add ceremony that doesn't pay off until you have very different shapes per state.

**Transitions are enforced at the tool boundary, not in the type system.** Each booking tool checks `cart.state` against the set of allowed source states for that operation, raises `ValueError` if the transition is invalid, and writes the new state to TinyDB. The model itself permits any state value at any time — defense lives in the tool layer.

```python
if cart.state not in {CartState.CREATED, CartState.ITEMS_ADDED}:
    raise ValueError(f"Cannot add items: cart is in state '{cart.state.value}'.")
```

### One-open-cart-per-user — idempotent constructors

`create_cart` returns the user's existing open cart (anything not `CONFIRMED`) instead of erroring or creating a duplicate. Same shape as `reserve_seats` and `generate_payment_link`: each constructor is **idempotent on its own state** — call it twice on a cart already in that state and you get the same record back. This makes the conversational LLM flow forgiving — "did I already start a cart?" never has to be answered, just call `create_cart` again.

### The snapshot pattern (price stability)

When `add_to_cart` runs, it calls `get_event_details(event_id)` and **copies** `event_name`, `unit_price`, and `currency` onto the `CartItem`:

```python
cart.items.append(CartItem(
    event_id=event_id,
    event_name=detail.name,
    quantity=quantity,
    unit_price=detail.price_min,
    currency=detail.price_currency,
))
```

If Ticketmaster updates the event's price 30 seconds later, the cart still reflects what the user agreed to. This is the same pattern real e-commerce uses — line items hold their own price; they never re-fetch at checkout. Without it, someone could "lock in" a price by adding to cart, then have the total silently change on them at payment.

### Merge-on-duplicate-add

Adding the same `event_id` twice doesn't create two line items — it sums the quantity into the existing one, capped at 10 per event. Cleaner cart UX than letting an LLM accidentally produce ten one-ticket lines for the same event.

### Seat-hold simulation — purely local

Real ticket platforms back reservations with seat-level locks in their inventory system. Ticketmaster has **no public hold endpoint**, so `reserve_seats` is a pure local state-machine operation: stamp `state = RESERVED`, set `expires_at = now + HOLD_MINUTES`, save. No HTTP call. We named the simulation honestly in code comments rather than pretending we're holding anything externally.

### Lazy expiry vs background sweep

A held reservation can lapse. Two ways to detect it:
- **Background sweep:** a periodic task scans for expired carts and demotes them.
- **Lazy on read:** every `_find_open_cart` call checks `expires_at` against `now()` and demotes if past.

We picked **lazy**. Reasons: (1) no background tasks, no asyncio scheduling, no concurrency edge cases; (2) the only thing that matters is that the next *operation* sees a coherent state; (3) for a single-user simulation, we will never observe a stale RESERVED cart in practice. The trade-off is that a never-read expired cart sits in the DB stale until someone touches it — fine for our scale.

When the demotion fires, we revert to `ITEMS_ADDED` (items survive — user can re-reserve) and clear `expires_at` and `payment_link`. Clearing the payment link matters because the link semantically referenced the now-lapsed hold.

### Mock payment URL — deterministically fake

`generate_payment_link` produces `https://payments.events-mcp.local/pay/{cart_id}`. The `.local` TLD doesn't resolve, the path is just the cart id, and the URL is **not** clickable to anything real. Two upsides:

1. **Deterministic by design** — same cart, same URL. Idempotency falls out for free; we just check `if cart.payment_link is None`.
2. **No PSP simulation drift** — we're not mocking what Stripe would do; we're explicitly *not* hitting Stripe. The fake-ness is part of the contract, not a stand-in for something.

The tool returns a `PaymentQuote` (separate from `Cart`) with `total`, `currency`, and a `has_unpriced_items: bool`. The flag matters because Ticketmaster events sometimes return without prices — we sum what we can and surface the gap rather than silently producing `total=0`.

### Manual confirmation, not auto-charge

`confirm_booking` requires `payment_link` to already be present on the cart. Generating the link does **not** advance the state or imply payment. The user is meant to click the link "externally" (in our sim, just acknowledge it exists) and then call `confirm_booking`. This enforces the CLAUDE.md ethics rule: *"Manual payment confirmation — never auto-charge, always generate a link and let user confirm."*

The `PAID` state exists in the enum but is never observable through tool calls. `confirm_booking` collapses `RESERVED → PAID → CONFIRMED` into one atomic write. We kept `PAID` as a model value anyway — costs nothing, and a future "two-step confirm" flow could split it out without a schema change.

### QR code generation — `qrcode[pil]`

The QR is the **entry ticket**, generated at `confirm_booking` time and returned as `qr_data_uri`. It is *not* the payment QR — that's `payment_link`. Two completely different things in the flow:

| Stage | Field | Form | Purpose |
|---|---|---|---|
| Payment | `payment_link` | URL string | User clicks → "pays" externally |
| Entry | `qr_data_uri` | data: URI (PNG) | Venue staff scan it at the gate |

We use the `qrcode` library (with the `[pil]` extra to pull in Pillow for PNG output):

```python
img = qrcode.make("events-mcp:booking/{booking_id}")
buf = io.BytesIO()
img.save(buf, format="PNG")
b64 = base64.b64encode(buf.getvalue()).decode("ascii")
return f"data:image/png;base64,{b64}"
```

The encoded payload is `events-mcp:booking/{booking_id}` — a self-describing opaque reference, **not** a URL. A phone scanner shows it as text. A real venue's scanner would look up the booking_id in their system. This keeps the QR honest about what it is: a reference, not a clickable link.

The `data:` URI lets any MCP client render the image inline without a separate file fetch — important because MCP clients aren't necessarily browsers.

### The Phase 5.5 seam

`confirm_booking` ends with a comment `# Phase 5.5 seam: email + calendar side effects fire here.` That's deliberate. Side effects (Resend email, Google Calendar deep link) hook onto the success branch *after* persistence — never before. If the email send fails, the booking is still saved. We don't want to roll back a confirmed booking because a notification provider had a bad afternoon.

---

## Phase 5.5 — Post-Booking Notifications

### Side effects vs the core flow

`confirm_booking` does two kinds of work in a defined order:

1. **Core flow** — finalize the cart and persist (`state = CONFIRMED`, save).
2. **Side effects** — Google Calendar deep links **and** the Resend email confirmation (with `.ics` attached).

Side effects run **after** persistence. If a calendar lookup or email send fails, the booking is already saved — we log the failure and continue. The user still gets their confirmed cart back; just one of the "extras" is missing. This is the correct shape for any system that does notifications: never roll back the *real* work because a notification provider had a bad afternoon.

```python
_save_cart(cart)                 # core — must succeed
log.info("booking_confirmed", ...)

# Side effects — failures captured, never raised.
event_details_by_id = await _fetch_unique_event_details(cart)
calendar_links = _build_calendar_links(cart, booking_id, event_details_by_id)
email_sent, email_skipped_reason = await send_booking_confirmation(...)

return BookingConfirmation(
    cart=cart,
    calendar_links=calendar_links,
    email_sent=email_sent,
    email_skipped_reason=email_skipped_reason,
)
```

### Google Calendar deep-link — pure URL construction, no auth

A Google Calendar "add event" link is just:

```
https://calendar.google.com/calendar/r/eventedit?text=...&dates=...&ctz=...&location=...&details=...
```

When the user clicks it, Google opens a pre-filled event-creation form on *their* calendar. No OAuth, no API call, no service account — just a string. We build it with `urllib.parse.urlencode` and return it.

**Why we picked this over the real Google Calendar API:** the real API requires OAuth 2.0 with the user's Google account, which means a consent flow and refresh-token storage. That's a Phase 6.5-shaped problem. The deep link gets us 90% of the UX with 5% of the code.

### Three branches of date handling

Ticketmaster's `dates.start` shape gives us three cases:

| Has `start_date` | Has `start_time` | Branch | Google `dates` format |
|---|---|---|---|
| ✅ | ✅ | Timed event | `YYYYMMDDTHHMMSS/YYYYMMDDTHHMMSS` + `ctz=<tz>` |
| ✅ | ❌ | All-day event | `YYYYMMDD/YYYYMMDD` (no `ctz`) |
| ❌ | — | Skip — return `None` | (caller skips this event) |

Two design choices worth flagging:

1. **`ctz` instead of UTC conversion.** Google accepts either `YYYYMMDDTHHMMSSZ` (UTC) or `YYYYMMDDTHHMMSS` + `ctz=America/New_York`. We use the second form. Reason: Ticketmaster gives us the local time and an IANA timezone. Doing the conversion to UTC ourselves means handling DST edge cases and weird timezones (Newfoundland, Lord Howe). Punting on it via `ctz` lets Google handle TZ math correctly.

2. **All-day event end is the *next day*.** Google's all-day format is `YYYYMMDD/YYYYMMDD` and the end day is *exclusive* — for a single-day all-day event, end = start + 1 day. Surprising at first; documented in the function's docstring so future-me doesn't try to "fix" it.

### `.ics` / iCalendar (RFC 5545) — the standard import format

The Google Calendar deep link is a one-click win for users on Google. But Apple Calendar, Outlook, and Fastmail don't follow that URL convention — they need a **file**. That's `.ics`: a plain UTF-8 text file in the iCalendar format (RFC 5545). Every desktop / mobile / web calendar app understands it.

A minimal `.ics` looks like:

```
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Coldplay — Music of the Spheres
DTSTART:20260515T233000Z
DTEND:20260516T023000Z
LOCATION:Madison Square Garden\, New York
UID:booking-abc:event-1@events-mcp
END:VEVENT
END:VCALENDAR
```

Things that are spec-mandated but easy to get wrong:

- **CRLF line endings** (`\r\n`), not `\n`. Many parsers tolerate `\n`, some don't.
- **Comma escaping** in text fields — `"Madison Square Garden, NY"` becomes `"Madison Square Garden\, NY"`. Same for `;` and `\`.
- **`UID`** must be globally unique and stable. We use `"<booking_id>:<event_id>@events-mcp"` so re-imports update the existing event in the user's calendar instead of creating a duplicate.
- **All-day events** use `DTSTART;VALUE=DATE:20260501` — the `VALUE=DATE` parameter swaps the type from datetime to date.
- **Timed events** with timezones either inline a `VTIMEZONE` block or render in UTC with the `Z` suffix. We do the latter — convert to UTC in Python, append `Z`, done.

We hand all of that to the `ics` library so we don't write a single escape rule ourselves.

### The `ics` library — composing VEVENT blocks without hand-rolling RFC 5545

`ics` (PyPI: [`ics`](https://pypi.org/project/ics/), v0.7.x) gives us two classes:

```python
from ics import Calendar, Event

cal = Calendar()
e = Event()
e.name = "Coldplay — Music of the Spheres"
e.uid = "booking-abc:event-1@events-mcp"
e.begin = datetime(2026, 5, 15, 19, 30, tzinfo=ZoneInfo("America/New_York"))
e.end = e.begin + timedelta(hours=3)
e.location = "Madison Square Garden, New York"
cal.events.add(e)

ics_text = cal.serialize()  # → str
```

A few things worth noting:

- **`begin` / `end` accept tz-aware datetimes** and serialize to UTC automatically (so `19:30 EDT` becomes `DTSTART:20260515T233000Z`). The library does the math we'd otherwise do with `astimezone(timezone.utc)`.
- **`make_all_day()`** flips an event to the `VALUE=DATE` form. Pass a date string to `begin` and call this method.
- **`str(cal)` is deprecated** in favor of `cal.serialize()` — `ics` raises a `FutureWarning` on `str(cal)`. Use the explicit method.
- **`begin` / `end` accept naive datetimes too** — but the library treats them as UTC silently, which is a footgun. Always pass tz-aware datetimes (we use `ZoneInfo` from stdlib).

`build_ics_text` is a **pure function** — takes a list of `ICSEventInput` dataclasses, returns the serialized text. No I/O, no Cart awareness, no preferences lookup. The caller composes the inputs from the cart and event details. Keeps the renderer trivially testable and reusable.

### Sharing the event-details fetch across side effects

Once we had two side effects that both need the per-event details (Google Calendar links **and** the email body / `.ics`), the Phase 5.5 commit-1 shape became wasteful:

```python
calendar_links = await _build_calendar_links(cart, booking_id)
# ↑ this internally calls get_event_details for every unique event
email = await send_booking_confirmation(cart, booking_id, ...)
# ↑ this would also need to call get_event_details for the same events
```

Even with the 15-min detail cache making repeat calls "free", the two helpers fetching independently meant duplicate code, two log entries per event, and an implicit dependency on the cache being warm. Refactor:

```python
event_details_by_id = await _fetch_unique_event_details(cart)
calendar_links = _build_calendar_links(cart, booking_id, event_details_by_id)
email = await send_booking_confirmation(cart, booking_id, event_details_by_id, ...)
```

Two side benefits fell out:

- `_build_calendar_links` is now **pure / sync** — it no longer does any I/O, just composes URLs from a dict it's handed. Easier to reason about, easier to test.
- The "fetch failed" log line (`event_detail_lookup_failed`) fires exactly once per event, regardless of how many side effects consume the result.

Lesson: when two side effects read the same external data, lift the read out and pass the result down. The cache made the "duplicate read" technically harmless, but it was *organizationally* messier.

### Re-fetch vs snapshot at add-time (the trade-off we made)

`CartItem` snapshots `event_name`, `unit_price`, `currency` — but **not** the date or venue. So `_build_calendar_links` calls `get_event_details(item.event_id)` per unique event in the cart at confirmation time.

Trade-off:
- **Re-fetch (chosen):** simpler model, no new fields on `CartItem`. The `get_event_details` cache (15-min TTL from Phase 3) means the call almost always hits cache for an event the user just added — effectively free.
- **Snapshot at add-time:** no extra calls at confirm time, but `CartItem` grows (date, venue, city, timezone, ...) and we'd be storing data that could go stale.

For a learning project at our scale the re-fetch is the right shape. If we ever scale to many bookings or want carts to survive without the API being available, snapshotting becomes the right answer.

### `BookingConfirmation` — wrapping the cart with side-effect outputs

`confirm_booking` previously returned `Cart`. With notifications joining the picture, the response shape needs to carry both the saved cart *and* the side-effect outputs:

```python
class BookingConfirmation(BaseModel):
    cart: Cart
    calendar_links: list[CalendarLink] = []
    email_sent: bool = False
    email_skipped_reason: str | None = None
```

**Why a wrapper rather than adding fields to `Cart`?** `Cart` is the persisted shape — what's in TinyDB. Notification outputs are response-only data; they're computed at confirmation time and never need to be re-read. Mixing them onto the storage model would mean either persisting them (waste) or making them transient on a stored model (confusing). Cleaner to keep `Cart` storage-shaped and let `BookingConfirmation` be the response shape.

**Why a `(bool, str | None)` shape instead of an enum or exception?** The two fields together encode three states: `(True, None)` = sent, `(False, "reason_str")` = skipped with explanation, `(False, None)` is unreachable (we always set a reason on skip). The string reason is a *closed set* (`resend_not_configured`, `no_email_in_preferences`, `resend_api_error`, `network_error`) but kept as `str` for forward-compat — adding a new reason doesn't require an enum migration. The LLM downstream sees the reason verbatim, which is more useful for natural-language relaying than an opaque enum value.

### Resend — transactional email API in one POST

[Resend](https://resend.com) is a transactional email service: you POST a JSON payload, their servers handle SPF/DKIM/MIME and deliver the message. Free tier is 100 emails/day, 3000/month — plenty for a learning project, and zero charge to fail-fast experiment.

The wire format is one HTTP call:

```
POST https://api.resend.com/emails
Authorization: Bearer re_xxx
Content-Type: application/json

{
  "from": "Events MCP <onboarding@resend.dev>",
  "to": ["user@example.com"],
  "subject": "Your booking is confirmed",
  "html": "<!doctype html>...",
  "attachments": [{"filename": "booking.ics", "content": [...], "content_type": "text/calendar; charset=utf-8"}]
}
```

We use the official `resend` Python SDK (a thin wrapper) instead of hand-rolling the call. Reason: the attachment encoding and the `SendParams` TypedDict take some of the friction away. We could equally well use `httpx` directly — the call is simple — but the SDK matched the shape of the rest of the project (typed params, named exception classes).

### Sender domain verification — why `onboarding@resend.dev`

Real email deliverability requires the sender's domain to publish DNS records (SPF, DKIM, DMARC) authorizing your provider to send on its behalf. If we tried `from: events@gmail.com`, Gmail's SPF check would see Resend's IPs, find no authorization in `gmail.com`'s DNS, and bounce the message.

Resend solves the "I just want to test this" problem by owning a dev sandbox domain — `resend.dev` — that's pre-configured with the right DNS. You can send `from: onboarding@resend.dev` to any address tied to your Resend account without setting anything up.

Caveats / what's actually allowed:

- **Only `onboarding@resend.dev` is whitelisted** for the sandbox. You can't claim other addresses on `resend.dev` — that's Resend's owned domain.
- **In free/dev mode you can only send to your own account email** until you verify a custom domain (so you can test without spamming strangers).
- **Display name is configurable** — `"Events MCP <onboarding@resend.dev>"` shows as "Events MCP" in the inbox, hiding the slightly-weird local-part.

Forward-compat: `RESEND_FROM` is a separate env var with that string as default. Swapping to `bookings@yourdomain.com` once a domain is verified is a one-line change.

### Sync vs async SDK methods — when `asyncio.to_thread` isn't needed

The Resend SDK exposes both sync and async variants for every operation — `Emails.send` and `Emails.send_async`. Same params, same response shape; the async one uses an internal `httpx` client instead of `requests`.

This matters because `confirm_booking` is async. With a sync-only SDK we'd have two options:
1. Call it from `asyncio.to_thread(...)` so the blocking I/O happens in a thread pool.
2. Just call it sync and accept the brief event-loop block.

Either works for ~100 emails/day, but the `send_async` variant lets us skip both — the SDK call is `await`able and integrates cleanly with our existing async stack:

```python
result = await resend.Emails.send_async(params)
```

Lesson: when picking a sync-by-default SDK, check for an `_async` variant before reaching for `to_thread`.

### Attachment encoding — `list[int]` vs base64 string

The `Attachment` TypedDict accepts `content` as either:
- A `list[int]` — i.e. `list(b"file bytes")`, raw bytes as a list of integers.
- A `str` — base64-encoded.

Both end up base64-encoded on the wire (Resend's API requires it). The `list[int]` form is the one their docs lead with, and it's slightly nicer because we don't have to call `base64.b64encode` ourselves:

```python
ics_text = build_ics_text(...)
attachment = {
    "filename": "booking.ics",
    "content": list(ics_text.encode("utf-8")),
    "content_type": "text/calendar; charset=utf-8",
}
```

**Why explicit `content_type`:** the SDK can derive it from the filename extension, but `.ics` isn't always recognized — and Apple Mail in particular renders the attachment quite differently if the MIME type is `text/plain` vs `text/calendar`. Set it explicitly.

### Optional config + graceful skip

`RESEND_API_KEY` is **optional** in our `Settings`. The whole booking flow has to keep working for someone running the server without an email provider configured (developers, CI, anyone exploring the booking sim).

```python
class Settings(BaseModel):
    resend_api_key: str | None = Field(None, ...)
    resend_from: str = Field(DEFAULT_RESEND_FROM, ...)
```

Two subtle bits:

1. **Empty string in `.env` (`RESEND_API_KEY=`) is treated the same as unset.** `os.environ.get("RESEND_API_KEY") or None` coerces `""` → `None`. Without that, we'd accept the empty key as "configured" and Resend would 401.
2. **The skip happens at the email module's entry, not in `confirm_booking`.** `send_booking_confirmation` checks `settings.resend_api_key` and `prefs.email` itself and returns `(False, "reason")`. The booking flow doesn't gate on either — it just collects the result and reports it back. That keeps the FSM clean and the email module fully responsible for its own preconditions.

### HTML escaping — why every interpolation goes through `html.escape`

Event names, venue names, city names, the booking ID — all of these flow into the email's HTML body. They came from Ticketmaster (which we treat as untrusted external data per CLAUDE.md's security rules), and the booking ID is server-generated UUID4 (so safe), but **uniform escaping is cheaper than reasoning about which fields are safe**.

```python
from html import escape as html_lib_escape  # stdlib, not jinja

f'<div style="font-weight:600;">{html_lib.escape(item.event_name)}</div>'
```

What this prevents:

- A Ticketmaster event titled `"Concert <script>alert(1)</script>"` becomes `"Concert &lt;script&gt;alert(1)&lt;/script&gt;"` — text, not executable JS. Most email clients sandbox JS anyway, but defense-in-depth.
- An event with quotes in the venue name (`"Madison Square \"the world's most famous arena\""`) won't break out of an HTML attribute and inject styles.

We'd reach for Jinja2 if the template grew much beyond what we have. For 100 lines of HTML composition, hand-rolled f-strings + `html.escape` is fine.

### Privacy contract — what the email module logs (and doesn't)

The module's docstring includes a privacy contract:

> The recipient email value is NEVER written to logs. Logs reference `user_id` and `cart_id` / `booking_id` only.

Concretely:

- `prefs.email` appears in exactly two places: the `to:` field of the Resend payload, and a falsy check (`if not prefs.email`).
- Failure logs include the **exception class name** and Resend's **status code** (useful for debugging) — never the address or the rendered HTML body.
- The success log records Resend's returned message ID (`resend_id`) so an operator can trace a delivery in the Resend dashboard, but nothing PII-bearing.

A single `grep "prefs.email\|to_email" notifications/email.py` confirms the address only flows into the API call, never into a log call. Worth running periodically as the module grows.

### Logging side-effect failures

Structured-log events introduced across the phase, all `lower_snake_case` past-tense per the project convention:

| Event | When | Notable fields |
|---|---|---|
| `calendar_links_built` | Once per confirm | `link_count` — "did anything generate?" |
| `calendar_link_skipped` | Per skipped event | `reason="no_start_date"` (closed set so queries filter cleanly) |
| `event_detail_lookup_failed` | Per event whose `get_event_details` raised | `event_id` only — no exception message (might contain API URL fragments) |
| `email_skipped` | Once per confirm if email path bails out | `reason` — one of `resend_not_configured`, `no_email_in_preferences` |
| `email_failed` | Once per confirm on Resend / network error | `reason`, `error_class`, `status_code` (when available) — never the address |
| `email_sent` | On success | `booking_id`, `resend_id` (Resend's message ID for tracing) |

All side-effect log lines reference `user_id` and `cart_id` so they can be traced back to a booking without logging PII.

### What we deliberately didn't do this phase

- **No timezone math for the Google deep link.** `ctz` punts it to Google. The `.ics` builder *does* convert to UTC (the `ics` library expects it) — different tools, different conventions.
- **No retries on `get_event_details` failure.** One try, log, skip. The booking is already saved; retrying is the user's call (re-confirm doesn't make sense — confirmation isn't idempotent for new links). A "regenerate calendar links for booking X" tool could be added later if needed.
- **No multi-currency support in the calendar `details` text.** We pass `Tickets: {qty}` but not the price/currency, because the calendar `details` field is meant to be human prose and prices were already shown at payment-link time.
- **No retries on Resend failure.** One attempt; surface `resend_api_error` / `network_error` and let the user retry by triggering a re-send tool we'll add later if needed. Auto-retry on transactional email is a footgun (duplicate messages on transient errors).
- **No email body localization or templating engine.** F-strings + `html.escape` for now; revisit if the template grows or we need multi-language.
- **No real Google Calendar API or Outlook write-back.** Both require OAuth — deferred to Phase 6.5 (auth) if/when we add it.
- **The `.ics` is attached to email but not surfaced in `BookingConfirmation`.** Decision was: email is the only delivery channel for the file. Easy to surface separately later if a non-email integration ever needs it.

---

## Phase 6 — HTTP Transport & Deployment ✅

### stdio vs. Streamable HTTP

**stdio** (what we used up to Phase 5.5) works by spawning the server as a child process and piping messages through stdin/stdout. Fast and zero-config locally, but can't be reached over the network.

**Streamable HTTP** makes the server a real HTTP service:
- `POST /mcp` — client sends a JSON-RPC message, server responds (standard request/response)
- `GET /mcp` — client opens an **SSE stream** for server-initiated messages (progress, notifications)

FastMCP handles both routes automatically when you call `mcp.run(transport="streamable-http")`.

---

### SSE (Server-Sent Events)

SSE is a simple HTTP-based protocol where the server keeps a connection open and pushes events as they happen. The client sends one `GET` with `Accept: text/event-stream`, and the server streams lines back in the format `data: ...\n\n`. It's one-directional (server → client only), which is all MCP needs for streaming.

This is why a plain `curl https://events-mcp.onrender.com/mcp` returns `406 Not Acceptable` — the server requires `Accept: text/event-stream` on GET requests.

---

### FastMCP `host` and `port`

These are **constructor parameters** on `FastMCP(...)`, not arguments to `mcp.run()`. They must be set before `run()` is called:

```python
mcp = FastMCP(
    "Events MCP",
    host=os.getenv("HOST", "127.0.0.1"),  # 0.0.0.0 in production
    port=int(os.getenv("PORT", "8000")),
)
```

Render injects `PORT` automatically. We add `HOST=0.0.0.0` manually so the server binds to all network interfaces (required for Render to detect the open port).

---

### Transport switching pattern

We use one env var to control transport mode so the same codebase works locally (stdio) and in production (HTTP):

```python
transport = os.getenv("MCP_TRANSPORT", "stdio")

if transport == "streamable-http":
    mcp.run(transport="streamable-http")
else:
    mcp.run()  # defaults to stdio
```

Local dev: no env var needed, stdio is the default.  
Render: `MCP_TRANSPORT=streamable-http` set in the dashboard.

---

### render.yaml — Infrastructure as Code

`render.yaml` in the repo root tells Render how to build and run the service:

```yaml
services:
  - type: web
    name: events-mcp
    runtime: python
    buildCommand: pip install uv && uv sync --frozen
    startCommand: uv run events-mcp
    envVars:
      - key: MCP_TRANSPORT
        value: streamable-http
      - key: HOST
        value: "0.0.0.0"
      - key: TICKETMASTER_API_KEY
        sync: false   # "fill this in the dashboard" — not stored in the file
```

`sync: false` means Render won't try to read the value from the file — it prompts you to set it manually in the dashboard. Use this for secrets.

---

### Ephemeral storage on Render free tier

Render's free tier does **not** persist the filesystem across deploys. Our TinyDB file (favorites, bookings) is wiped on each redeploy. Acceptable for a learning project. The fix for production would be to swap TinyDB for Render's free PostgreSQL add-on.

---

### Live URL

```
https://events-mcp.onrender.com/mcp
```

Any MCP-compatible client can now connect by pointing at this URL.

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
