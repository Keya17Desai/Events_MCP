"""Pydantic models for the simulated booking flow.

A Cart moves through a finite state machine:

    CREATED → ITEMS_ADDED → RESERVED → PAID → CONFIRMED

Each transition is enforced in the booking tools (events_mcp.tools.booking),
not in the type system. We keep a single Cart model with optional
state-specific fields rather than a discriminated union — simpler for now
and adequate while the FSM is small.

Field availability by state:
- CREATED       → cart_id, user_id, state, items=[], created_at, updated_at
- ITEMS_ADDED   → + items populated
- RESERVED      → + expires_at
- PAID          → + payment_link, paid_at
- CONFIRMED     → + booking_id, confirmed_at, qr_data_uri (expires_at cleared)
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class CartState(StrEnum):
    CREATED = "created"
    ITEMS_ADDED = "items_added"
    RESERVED = "reserved"
    PAID = "paid"
    CONFIRMED = "confirmed"


class CartItem(BaseModel):
    """One line item in a cart. Snapshots event name and price at add-time."""

    event_id: str = Field(..., description="Ticketmaster event id")
    event_name: str = Field(..., description="Snapshot of event name at add-time")
    quantity: int = Field(..., ge=1, le=10, description="Number of tickets")
    unit_price: float | None = Field(
        None,
        description="Snapshot of price_min at add-time; null if event was unpriced",
    )
    currency: str | None = Field(
        None,
        description="Currency code from the event (e.g. 'USD'); null if unpriced",
    )


class Cart(BaseModel):
    """A booking cart. One open cart per user at a time."""

    cart_id: str = Field(..., description="UUID4 string identifying the cart")
    user_id: str
    state: CartState
    items: list[CartItem] = Field(default_factory=list)

    created_at: str = Field(..., description="ISO 8601 UTC timestamp")
    updated_at: str = Field(..., description="ISO 8601 UTC timestamp")

    expires_at: str | None = Field(
        None,
        description="When the seat hold expires (RESERVED state only)",
    )

    payment_link: str | None = Field(
        None,
        description="Fake payment URL (sim only — no real provider)",
    )
    paid_at: str | None = None

    booking_id: str | None = Field(
        None,
        description="UUID4 of the confirmed booking; null until CONFIRMED",
    )
    confirmed_at: str | None = None
    qr_data_uri: str | None = Field(
        None,
        description="Base64-encoded QR PNG as a data URI; only set on CONFIRMED",
    )
