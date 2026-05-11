# Events MCP Server

An MCP (Model Context Protocol) server for discovering and booking live events — concerts, sports, theater, festivals — powered by the [Ticketmaster Discovery API](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/).

Connect it to any MCP-compatible AI client (Claude Code, Claude Desktop) and search, save, and "book" events using plain English.

---

## Live Server

```
https://events-mcp.onrender.com/mcp
```

**Connect via Claude Code:**
```bash
claude mcp add events-mcp --transport streamable-http https://events-mcp.onrender.com/mcp
```

**Connect via Claude Desktop** — add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "events-mcp": {
      "url": "https://events-mcp.onrender.com/mcp"
    }
  }
}
```

---

## What You Can Do

Once connected, just talk to Claude naturally:

```
"Find rock concerts in Mumbai this weekend under ₹2000"
"Save the Coldplay event to my favorites"
"What events would I like based on my preferences?"
"Book 2 tickets for event G5vYZ4YXFZ5Vb"
"Send me a confirmation email and add it to my Google Calendar"
```

---

## Tools Reference

### Discovery
| Tool | Description |
|---|---|
| `search_events` | Search live events by city, keyword, category, or date range |
| `get_event_details` | Full details for one event (description, prices, performers, seatmap) |
| `search_venues` | Find venues by name or city |
| `search_attractions` | Look up artists, teams, or performers |

### Favorites & Preferences
| Tool | Description |
|---|---|
| `save_favorite` | Save an event to your favorites list |
| `list_favorites` | List all saved favorites |
| `remove_favorite` | Remove an event from favorites |
| `set_preferences` | Set your city, genres, currency, and email for confirmations |
| `get_preferences` | Retrieve your stored preferences |
| `get_recommendations` | Get event recommendations based on your preferences |

### Booking (Simulated)
| Tool | Description |
|---|---|
| `create_cart` | Open a new booking cart |
| `add_to_cart` | Add tickets for an event to your cart |
| `get_cart` | View current cart contents and state |
| `reserve_seats` | Lock in a 10-minute seat hold |
| `generate_payment_link` | Generate a mock payment link with total |
| `confirm_booking` | Finalize the booking — triggers email + Google Calendar link |

### Prompts (slash commands)
| Prompt | Description |
|---|---|
| `/event_night_plan` | Build an evening itinerary for a city and date |
| `/genre_picks` | Curated picks for a genre fan |
| `/compare_events` | Side-by-side comparison of two events |
| `/surprise_me` | One off-the-beaten-path event with a pitch |

---

## Booking Flow

The booking flow is a **simulated state machine** — no real payment is processed. It demonstrates the full conversational booking experience:

```
create_cart → add_to_cart → reserve_seats → generate_payment_link → confirm_booking
                                                                           ↓
                                                              email confirmation (Resend)
                                                              Google Calendar deep link
```

After `confirm_booking`:
- An HTML email with a `.ics` calendar attachment is sent to your stored email (set via `set_preferences`)
- A Google Calendar deep link is returned so you can add the event in one click

---

## Local Development

**Prerequisites:** Python 3.12+, [`uv`](https://github.com/astral-sh/uv)

```bash
# Clone and install
git clone https://github.com/Keya17Desai/Events_MCP.git
cd Events_MCP
uv sync

# Configure secrets
cp .env.example .env
# Edit .env — add your TICKETMASTER_API_KEY (and optionally RESEND_API_KEY)

# Run locally (stdio mode — for Claude Code)
uv run events-mcp

# Run as HTTP server (for browser testing)
MCP_TRANSPORT=streamable-http uv run events-mcp
# Server at http://localhost:8000

# Debug with MCP Inspector
uv run mcp dev src/events_mcp/server.py
```

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12 |
| Package manager | `uv` |
| MCP framework | `mcp[cli]` + FastMCP |
| Schema validation | Pydantic v2 |
| HTTP client | `httpx` (async) |
| Caching | `cachetools` (TTL-based) |
| Rate limiting | `aiolimiter` |
| Logging | `structlog` (JSON in prod, colored in dev) |
| Local storage | `tinydb` |
| Email | `resend` |
| Calendar | `ics` (iCalendar) |
| Data source | Ticketmaster Discovery API |
| Deployment | Render (free tier) |

---

## Project Structure

```
src/events_mcp/
├── server.py              # FastMCP app, tool registration
├── config.py              # Env loading (pydantic-settings)
├── logging.py             # structlog setup
├── clients/
│   └── ticketmaster.py    # Async httpx wrapper + caching + rate limiting
├── tools/
│   ├── discovery.py       # search_events, get_event_details, ...
│   ├── favorites.py       # save/list/remove favorites, preferences, recommendations
│   └── booking.py         # Cart state machine (create → confirm)
├── prompts/
│   └── discovery.py       # MCP Prompts (event_night_plan, genre_picks, ...)
├── notifications/
│   ├── email.py           # Resend integration
│   └── calendar.py        # .ics builder + Google Calendar URL
├── models/                # Pydantic response models
├── storage/
│   └── db.py              # TinyDB setup, user-namespaced tables
└── utils/
    ├── cache.py
    └── rate_limit.py
```

---

## Security Notes

- All tool inputs validated with Pydantic v2 (strict mode)
- API keys loaded from environment variables only — never hardcoded
- Email addresses are never logged (flow: preferences → Resend → done)
- No shell commands executed from tool inputs

---

## Limitations

- **Booking is simulated** — no real tickets are purchased or payment processed
- **Storage is ephemeral on Render free tier** — favorites and bookings reset on redeploy
- **Single-user** — all data stored under `default_user`; multi-user auth is a planned future phase
- **Ticketmaster coverage** — event data is strongest for US/UK/CA markets
