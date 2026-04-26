"""Booking flow tools (Phase 5).

Implements a finite state machine: a Cart moves from CREATED through
ITEMS_ADDED, RESERVED, PAID, and finally CONFIRMED. Invalid transitions
are rejected at the tool boundary, not silently ignored.

All carts are namespaced under a user_id (DEFAULT_USER_ID for now;
real auth plugs in here in Phase 6.5 without a schema migration).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from tinydb import Query

from events_mcp.logging import get_logger
from events_mcp.models.cart import Cart, CartState
from events_mcp.storage.db import DEFAULT_USER_ID, carts_table

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_cart() -> Cart:
    """Open a new booking cart, or return the user's existing open cart.

    A user has at most one open cart at a time. "Open" means any state
    other than CONFIRMED. If an open cart already exists, this tool
    returns it unchanged — callers can treat it as idempotent.
    """
    table = carts_table()
    C = Query()

    existing = table.search(
        (C.user_id == DEFAULT_USER_ID) & (C.state != CartState.CONFIRMED.value)
    )
    if existing:
        log.info(
            "cart_returned_existing",
            user_id=DEFAULT_USER_ID,
            cart_id=existing[0]["cart_id"],
            state=existing[0]["state"],
        )
        return Cart.model_validate(existing[0])

    now = _now_iso()
    cart = Cart(
        cart_id=str(uuid.uuid4()),
        user_id=DEFAULT_USER_ID,
        state=CartState.CREATED,
        items=[],
        created_at=now,
        updated_at=now,
    )
    table.insert(cart.model_dump(mode="json"))
    log.info("cart_created", user_id=DEFAULT_USER_ID, cart_id=cart.cart_id)
    return cart
