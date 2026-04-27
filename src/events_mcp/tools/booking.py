"""Booking flow tools (Phase 5).

Implements a finite state machine: a Cart moves from CREATED through
ITEMS_ADDED, RESERVED, PAID, and finally CONFIRMED. Invalid transitions
are rejected at the tool boundary, not silently ignored.

All carts are namespaced under a user_id (DEFAULT_USER_ID for now;
real auth plugs in here in Phase 6.5 without a schema migration).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import Field
from tinydb import Query

from events_mcp.logging import get_logger
from events_mcp.models.cart import Cart, CartItem, CartState, PaymentQuote
from events_mcp.storage.db import DEFAULT_USER_ID, carts_table
from events_mcp.tools.discovery import get_event_details

log = get_logger(__name__)

MAX_QUANTITY_PER_EVENT = 10
HOLD_MINUTES = 10
PAYMENT_LINK_BASE = "https://payments.events-mcp.local/pay"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_expiry(cart: Cart) -> Cart:
    """Lazily demote an expired RESERVED cart back to ITEMS_ADDED.

    Persists the demotion if it happens. No-op for any other state or
    for a still-valid hold.
    """
    if cart.state != CartState.RESERVED or cart.expires_at is None:
        return cart

    expires = datetime.fromisoformat(cart.expires_at)
    if datetime.now(timezone.utc) < expires:
        return cart

    cart.state = CartState.ITEMS_ADDED
    cart.expires_at = None
    cart.payment_link = None
    cart.updated_at = _now_iso()
    _save_cart(cart)
    log.info(
        "cart_reservation_expired",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
    )
    return cart


def _find_open_cart() -> Cart | None:
    """Return the user's open (non-CONFIRMED) cart, or None if no cart is open.

    Lazy-demotes a RESERVED cart whose hold has lapsed back to ITEMS_ADDED
    before returning, so every caller sees a coherent state.
    """
    table = carts_table()
    C = Query()
    rows = table.search(
        (C.user_id == DEFAULT_USER_ID) & (C.state != CartState.CONFIRMED.value)
    )
    if not rows:
        return None
    return _apply_expiry(Cart.model_validate(rows[0]))


def _require_open_cart() -> Cart:
    cart = _find_open_cart()
    if cart is None:
        raise ValueError(
            "No open cart. Call create_cart first to start a booking."
        )
    return cart


def _save_cart(cart: Cart) -> None:
    """Persist the cart back to the carts table, keyed by cart_id."""
    table = carts_table()
    C = Query()
    table.update(cart.model_dump(mode="json"), C.cart_id == cart.cart_id)


def create_cart() -> Cart:
    """Open a new booking cart, or return the user's existing open cart.

    A user has at most one open cart at a time. "Open" means any state
    other than CONFIRMED. If an open cart already exists, this tool
    returns it unchanged — callers can treat it as idempotent.
    """
    existing = _find_open_cart()
    if existing is not None:
        log.info(
            "cart_returned_existing",
            user_id=DEFAULT_USER_ID,
            cart_id=existing.cart_id,
            state=existing.state.value,
        )
        return existing

    now = _now_iso()
    cart = Cart(
        cart_id=str(uuid.uuid4()),
        user_id=DEFAULT_USER_ID,
        state=CartState.CREATED,
        items=[],
        created_at=now,
        updated_at=now,
    )
    carts_table().insert(cart.model_dump(mode="json"))
    log.info("cart_created", user_id=DEFAULT_USER_ID, cart_id=cart.cart_id)
    return cart


def get_cart() -> Cart:
    """Return the user's currently open cart.

    Raises if no open cart exists — call create_cart first.
    """
    cart = _require_open_cart()
    log.info(
        "cart_read",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
        state=cart.state.value,
        items_count=len(cart.items),
    )
    return cart


async def add_to_cart(
    event_id: Annotated[
        str,
        Field(
            description="Ticketmaster event id (from search_events)",
            min_length=1,
            strict=True,
        ),
    ],
    quantity: Annotated[
        int,
        Field(
            description="Number of tickets to add (1-10)",
            ge=1,
            le=MAX_QUANTITY_PER_EVENT,
            strict=True,
        ),
    ] = 1,
) -> Cart:
    """Add tickets for an event to the user's open cart.

    - Snapshots event_name and unit_price (price_min) at add-time, so
      cart contents stay stable even if the event's price changes.
    - Adding the same event again merges into the existing line item
      (sums quantity, capped at 10 per event).
    - Only allowed when the cart is in CREATED or ITEMS_ADDED state;
      reserved/paid/confirmed carts cannot be modified.
    """
    cart = _require_open_cart()

    if cart.state not in {CartState.CREATED, CartState.ITEMS_ADDED}:
        raise ValueError(
            f"Cannot add items: cart is in state '{cart.state.value}'. "
            f"Items can only be added before reservation."
        )

    detail = await get_event_details(event_id)

    existing_idx = next(
        (i for i, item in enumerate(cart.items) if item.event_id == event_id),
        None,
    )
    merged = existing_idx is not None

    if existing_idx is not None:
        existing = cart.items[existing_idx]
        new_qty = existing.quantity + quantity
        if new_qty > MAX_QUANTITY_PER_EVENT:
            raise ValueError(
                f"Cannot add {quantity}: would exceed max quantity of "
                f"{MAX_QUANTITY_PER_EVENT} per event "
                f"(current: {existing.quantity})."
            )
        cart.items[existing_idx] = CartItem(
            event_id=existing.event_id,
            event_name=existing.event_name,
            quantity=new_qty,
            unit_price=existing.unit_price,
            currency=existing.currency,
        )
    else:
        cart.items.append(
            CartItem(
                event_id=event_id,
                event_name=detail.name,
                quantity=quantity,
                unit_price=detail.price_min,
                currency=detail.price_currency,
            )
        )

    cart.state = CartState.ITEMS_ADDED
    cart.updated_at = _now_iso()
    _save_cart(cart)

    log.info(
        "cart_item_added",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
        event_id=event_id,
        quantity=quantity,
        merged=merged,
        items_count=len(cart.items),
    )
    return cart


def reserve_seats() -> Cart:
    """Promote the user's open cart from ITEMS_ADDED to RESERVED.

    Stamps an expires_at timestamp HOLD_MINUTES into the future. While
    RESERVED, the cart cannot be modified — calling reserve_seats again
    refreshes the hold (idempotent extend). If the hold lapses, the
    cart auto-reverts to ITEMS_ADDED on the next read so the user can
    retry without losing items.

    Real ticket platforms back this with seat-level locks; ours is a
    pure local state machine — no Ticketmaster call.
    """
    cart = _require_open_cart()

    if cart.state in {CartState.PAID, CartState.CONFIRMED}:
        raise ValueError(
            f"Cannot reserve: cart is in state '{cart.state.value}'."
        )

    if not cart.items:
        raise ValueError(
            "Cannot reserve an empty cart. Add at least one item first."
        )

    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=HOLD_MINUTES)
    cart.state = CartState.RESERVED
    cart.expires_at = expires.isoformat()
    cart.updated_at = now.isoformat()
    _save_cart(cart)

    log.info(
        "cart_reserved",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
        expires_at=cart.expires_at,
        hold_minutes=HOLD_MINUTES,
        items_count=len(cart.items),
    )
    return cart


def _compute_total(items: list[CartItem]) -> tuple[float, str | None, bool]:
    """Return (total, currency, has_unpriced_items) for a list of items.

    Unpriced items contribute 0 to the total. Currency is the first
    non-null currency we see; mixed-currency carts are not supported
    and are not enforced here (Ticketmaster events each have their own).
    """
    total = 0.0
    currency: str | None = None
    has_unpriced = False
    for item in items:
        if item.unit_price is None:
            has_unpriced = True
            continue
        total += item.unit_price * item.quantity
        if currency is None:
            currency = item.currency
    return total, currency, has_unpriced


def generate_payment_link() -> PaymentQuote:
    """Generate a mock payment link for the user's RESERVED cart.

    The cart must already be RESERVED — call reserve_seats first. The
    link is a fake URL (the events-mcp.local domain doesn't resolve);
    it stands in for a real PSP redirect so we can demo the flow
    without a payment provider.

    Idempotent: calling twice on the same RESERVED cart returns the
    same link. If the hold lapsed and the cart was demoted, a later
    re-reservation gets a fresh link (lapse clears payment_link).

    Items with no price contribute 0 to the total, and has_unpriced_items
    is set so the LLM can warn the user before they "pay".
    """
    cart = _require_open_cart()

    if cart.state != CartState.RESERVED:
        raise ValueError(
            f"Cannot generate payment link: cart is in state "
            f"'{cart.state.value}'. Call reserve_seats first."
        )

    if cart.payment_link is None:
        cart.payment_link = f"{PAYMENT_LINK_BASE}/{cart.cart_id}"
        cart.updated_at = _now_iso()
        _save_cart(cart)
        log.info(
            "payment_link_generated",
            user_id=DEFAULT_USER_ID,
            cart_id=cart.cart_id,
        )
    else:
        log.info(
            "payment_link_returned_existing",
            user_id=DEFAULT_USER_ID,
            cart_id=cart.cart_id,
        )

    total, currency, has_unpriced = _compute_total(cart.items)
    return PaymentQuote(
        cart_id=cart.cart_id,
        payment_link=cart.payment_link,
        total=total,
        currency=currency,
        has_unpriced_items=has_unpriced,
        expires_at=cart.expires_at,
    )
