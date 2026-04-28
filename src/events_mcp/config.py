"""Configuration loader for the Events MCP server.

Reads .env (if present) and exposes validated settings via get_settings().
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()


DEFAULT_RESEND_FROM = "Events MCP <onboarding@resend.dev>"


class Settings(BaseModel):
    """Validated, immutable runtime configuration."""

    model_config = {"frozen": True}

    ticketmaster_api_key: str = Field(
        ...,
        min_length=10,
        description="Ticketmaster Discovery API consumer key",
    )

    resend_api_key: str | None = Field(
        None,
        description=(
            "Resend transactional email API key. Optional — when missing, "
            "booking-confirmation emails are skipped (booking still succeeds)."
        ),
    )
    resend_from: str = Field(
        DEFAULT_RESEND_FROM,
        description=(
            "From address for booking emails. Default uses Resend's pre-verified "
            "sandbox sender. Override via RESEND_FROM once you verify a custom domain."
        ),
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

    # Empty string in .env (e.g. `RESEND_API_KEY=`) is treated the same as
    # unset — both mean "email is not configured", not "invalid empty key".
    resend_key = os.environ.get("RESEND_API_KEY") or None
    resend_from = os.environ.get("RESEND_FROM") or DEFAULT_RESEND_FROM

    try:
        return Settings(
            ticketmaster_api_key=api_key,
            resend_api_key=resend_key,
            resend_from=resend_from,
        )
    except ValidationError as e:
        raise RuntimeError(f"Invalid configuration: {e}") from e
