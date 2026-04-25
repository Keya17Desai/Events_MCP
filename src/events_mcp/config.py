"""Configuration loader for the Events MCP server.

Reads .env (if present) and exposes validated settings via get_settings().
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()


class Settings(BaseModel):
    """Validated, immutable runtime configuration."""

    model_config = {"frozen": True}

    ticketmaster_api_key: str = Field(
        ...,
        min_length=10,
        description="Ticketmaster Discovery API consumer key",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate runtime settings. Cached after first call.

    Raises RuntimeError on missing or invalid configuration.
    """
    api_key = os.environ.get("TICKETMASTER_API_KEY")
    if api_key is None:
        raise RuntimeError(
            "Missing required environment variable TICKETMASTER_API_KEY. "
            "Copy .env.example to .env and fill in your Ticketmaster consumer key."
        )
    try:
        return Settings(ticketmaster_api_key=api_key)
    except ValidationError as e:
        raise RuntimeError(f"Invalid configuration: {e}") from e
