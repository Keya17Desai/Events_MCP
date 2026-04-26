"""TinyDB storage layer.

A single JSON file at data/db.json holds two tables:
- favorites: events the user has saved
- preferences: their settings (email, preferred_city, etc.)

Every record is namespaced under a `user_id`. We hardcode "default_user"
for now; this is the seam where real auth (Phase 6.5) will plug in
without a schema migration.

Override the file location with EVENTS_MCP_DB_PATH if needed (useful
for tests).
"""
from __future__ import annotations

import os
from pathlib import Path

from tinydb import TinyDB
from tinydb.table import Table

DEFAULT_USER_ID = "default_user"


def _resolve_db_path() -> Path:
    if env_path := os.environ.get("EVENTS_MCP_DB_PATH"):
        return Path(env_path)
    # src/events_mcp/storage/db.py → project root is parents[3]
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "data" / "db.json"


DB_PATH = _resolve_db_path()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_db = TinyDB(DB_PATH, indent=2)


def favorites_table() -> Table:
    return _db.table("favorites")


def preferences_table() -> Table:
    return _db.table("preferences")


def carts_table() -> Table:
    return _db.table("carts")
