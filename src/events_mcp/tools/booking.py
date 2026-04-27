"""Booking flow tools (Phase 5).

Implements a finite state machine: a Cart moves from CREATED through
ITEMS_ADDED, RESERVED, PAID, and finally CONFIRMED. Invalid transitions
are rejected at the tool boundary, not silently ignored.

All carts are namespaced under a user_id (DEFAULT_USER_ID for now;
real auth plugs in here in Phase 6.5 without a schema migration).
"""
from __future__ import annotations

import base64
import io
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import qrcode
from pydantic import Field
from tinydb import Query

from events_mcp.clients.ticketmaster import TicketmasterAPIError
from events_mcp.logging import get_logger
from events_mcp.models.cart import (
    BookingConfirmation,
    CalendarLink,
    Cart,
    CartItem,
    CartState,
    PaymentQuote,
)
from events_mcp.notifications.calendar import build_google_calendar_url
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


def _make_qr_data_uri(payload: str) -> str:
    """Encode payload as a PNG QR code, return as a data: URI."""
    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


async def confirm_booking() -> BookingConfirmation:
    """Finalize the booking. RESERVED → CONFIRMED.

    Requires a payment_link (i.e. generate_payment_link must have been
    called first) — this stands in for "the user clicked the link and
    paid". Stamps booking_id, paid_at, confirmed_at, and a real QR
    PNG (as a data: URI) encoding the booking reference for venue
    entry. Clears expires_at since the seat hold no longer applies.

    Returns a BookingConfirmation wrapping the saved cart and any
    side-effect outputs — currently a list of Google Calendar deep
    links (one per unique event in the cart) so the user can add the
    event(s) to their own calendar with one click.

    Side-effect failures (e.g. calendar lookup) do NOT roll back the
    booking — the cart stays CONFIRMED and the relevant link is just
    omitted with a logged reason.

    Once confirmed, the cart is no longer "open" — a subsequent
    create_cart will start a fresh one.
    """
    cart = _require_open_cart()

    if cart.state != CartState.RESERVED:
        raise ValueError(
            f"Cannot confirm: cart is in state '{cart.state.value}'. "
            f"Call reserve_seats first."
        )

    if cart.payment_link is None:
        raise ValueError(
            "Cannot confirm: no payment link on cart. "
            "Call generate_payment_link first."
        )

    now = _now_iso()
    booking_id = str(uuid.uuid4())
    cart.state = CartState.CONFIRMED
    cart.booking_id = booking_id
    cart.paid_at = now
    cart.confirmed_at = now
    cart.qr_data_uri = _make_qr_data_uri(f"events-mcp:booking/{booking_id}")
    cart.expires_at = None
    cart.updated_at = now
    _save_cart(cart)

    log.info(
        "booking_confirmed",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
        booking_id=booking_id,
        items_count=len(cart.items),
    )

    calendar_links = await _build_calendar_links(cart, booking_id)
    return BookingConfirmation(cart=cart, calendar_links=calendar_links)


async def _build_calendar_links(
    cart: Cart, booking_id: str
) -> list[CalendarLink]:
    """Build one Google Calendar deep link per unique event in the cart.

    Skips events whose details we can't fetch (logged) or that have no
    start_date (logged). Never raises — notification failures must not
    roll back a saved booking.
    """
    links: list[CalendarLink] = []
    seen: set[str] = set()
    for item in cart.items:
        if item.event_id in seen:
            continue
        seen.add(item.event_id)

        try:
            detail = await get_event_details(item.event_id)
        except TicketmasterAPIError:
            log.warning(
                "calendar_link_lookup_failed",
                user_id=DEFAULT_USER_ID,
                event_id=item.event_id,
            )
            continue

        location_parts = [p for p in (detail.venue_name, detail.city) if p]
        location = ", ".join(location_parts) if location_parts else None
        details_text = (
            f"Booking {booking_id} via Events MCP. "
            f"Tickets: {item.quantity}."
        )

        url = build_google_calendar_url(
            title=detail.name,
            start_date=detail.start_date,
            start_time=detail.start_time,
            timezone=detail.timezone,
            location=location,
            details=details_text,
        )

        if url is None:
            log.info(
                "calendar_link_skipped",
                user_id=DEFAULT_USER_ID,
                event_id=item.event_id,
                reason="no_start_date",
            )
            continue

        links.append(
            CalendarLink(
                event_id=item.event_id,
                event_name=item.event_name,
                url=url,
            )
        )

    log.info(
        "calendar_links_built",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
        link_count=len(links),
    )
    return links
