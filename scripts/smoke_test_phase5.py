"""Smoke test: Phase 5 — booking flow.

Covers the full booking state machine: create → add → reserve →
generate_payment_link → confirm_booking, plus error/edge paths
(empty reserve, hold lapse, missing payment link, etc.).

The test wipes the user's carts at the start so it's safely re-runnable.
We use the storage table directly for cleanup since Phase 5 deliberately
doesn't expose a cancel/delete cart tool.

Run with:
    uv run python scripts/smoke_test_phase5.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from tinydb import Query

from events_mcp.logging import configure_logging
from events_mcp.models.cart import CartState
from events_mcp.storage.db import DEFAULT_USER_ID, carts_table
from events_mcp.tools.booking import (
    add_to_cart,
    confirm_booking,
    create_cart,
    generate_payment_link,
    get_cart,
    reserve_seats,
)
from events_mcp.tools.discovery import search_events


def _section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def _wipe_user_carts() -> None:
    table = carts_table()
    C = Query()
    table.remove(C.user_id == DEFAULT_USER_ID)


async def main() -> None:
    configure_logging()
    _wipe_user_carts()

    _section("0. Find a real event id to add")
    search = await search_events(city="New York", size=1, sort="date,asc")
    if not search.events:
        print("No events returned — can't run the rest of the test.")
        return
    event = search.events[0]
    print(f"Using event: {event.name} ({event.id})")

    _section("1. create_cart — first call")
    cart = create_cart()
    print(f"cart_id={cart.cart_id}  state={cart.state}  items={len(cart.items)}")
    assert cart.state == CartState.CREATED

    _section("2. create_cart again — should return same open cart")
    cart2 = create_cart()
    assert cart.cart_id == cart2.cart_id, "expected same open cart back"
    print("OK: same cart_id returned (one open cart per user)")

    _section("3. get_cart — should return the open cart")
    got = get_cart()
    assert got.cart_id == cart.cart_id
    assert got.state == CartState.CREATED
    print(f"OK: state={got.state}, items={len(got.items)}")

    _section("3a. reserve_seats — empty cart should fail")
    try:
        reserve_seats()
    except ValueError as e:
        print(f"OK: rejected with — {e}")
    else:
        raise AssertionError("expected ValueError reserving an empty cart")

    _section("4. add_to_cart — add 2 tickets for the event")
    cart = await add_to_cart(event_id=event.id, quantity=2)
    assert cart.state == CartState.ITEMS_ADDED
    assert len(cart.items) == 1
    assert cart.items[0].quantity == 2
    print(f"items={len(cart.items)}  qty={cart.items[0].quantity}  state={cart.state}")
    print(f"  snapshotted: name='{cart.items[0].event_name}'  unit_price={cart.items[0].unit_price}")

    _section("5. add_to_cart same event again — should MERGE (qty 2 + 1 = 3)")
    cart = await add_to_cart(event_id=event.id, quantity=1)
    assert len(cart.items) == 1, "merge should not create a new line item"
    assert cart.items[0].quantity == 3, "quantity should sum to 3"
    print(f"OK: still {len(cart.items)} item, qty now {cart.items[0].quantity}")

    _section("6. add_to_cart — exceeding cap should raise")
    try:
        await add_to_cart(event_id=event.id, quantity=8)  # 3 + 8 = 11, over cap
    except ValueError as e:
        print(f"OK: rejected with — {e}")
    else:
        raise AssertionError("expected ValueError for quantity over cap")

    _section("7. get_cart — confirms state persisted")
    final = get_cart()
    assert final.state == CartState.ITEMS_ADDED
    assert final.items[0].quantity == 3
    print(f"OK: state={final.state}, qty={final.items[0].quantity}")

    _section("8. reserve_seats — should succeed and stamp expires_at")
    reserved = reserve_seats()
    assert reserved.state == CartState.RESERVED
    assert reserved.expires_at is not None
    print(f"OK: state={reserved.state}  expires_at={reserved.expires_at}")

    _section("9. add_to_cart on RESERVED cart — should fail")
    try:
        await add_to_cart(event_id=event.id, quantity=1)
    except ValueError as e:
        print(f"OK: rejected with — {e}")
    else:
        raise AssertionError("expected ValueError adding to a reserved cart")

    _section("10. reserve_seats again — should refresh expires_at")
    first_expires = reserved.expires_at
    re_reserved = reserve_seats()
    assert re_reserved.state == CartState.RESERVED
    assert re_reserved.expires_at >= first_expires
    print(f"OK: refreshed expires_at  (was {first_expires}, now {re_reserved.expires_at})")

    _section("11. simulate hold expiry — backdate expires_at, get_cart should demote")
    table = carts_table()
    C = Query()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    table.update({"expires_at": past}, C.cart_id == re_reserved.cart_id)
    after_expiry = get_cart()
    assert after_expiry.state == CartState.ITEMS_ADDED, "expected demotion to ITEMS_ADDED"
    assert after_expiry.expires_at is None
    print(f"OK: state={after_expiry.state}, expires_at cleared")

    _section("12. add_to_cart works again after expiry")
    cart = await add_to_cart(event_id=event.id, quantity=1)
    assert cart.state == CartState.ITEMS_ADDED
    assert cart.items[0].quantity == 4
    print(f"OK: qty now {cart.items[0].quantity}")

    _section("13. generate_payment_link before reserve — should fail")
    try:
        generate_payment_link()
    except ValueError as e:
        print(f"OK: rejected with — {e}")
    else:
        raise AssertionError("expected ValueError generating link before reserve")

    _section("14. generate_payment_link after reserve — should succeed")
    reserve_seats()
    quote = generate_payment_link()
    assert quote.cart_id == cart.cart_id
    assert quote.payment_link.endswith(cart.cart_id)
    expected_total = sum(
        (i.unit_price or 0) * i.quantity for i in cart.items
    )
    assert quote.total == expected_total, (quote.total, expected_total)
    print(
        f"OK: link={quote.payment_link}  total={quote.total} {quote.currency}  "
        f"has_unpriced={quote.has_unpriced_items}"
    )

    _section("15. generate_payment_link again — idempotent (same link)")
    quote2 = generate_payment_link()
    assert quote2.payment_link == quote.payment_link
    print("OK: same payment_link returned")

    _section("16. lapse clears payment_link; re-reserve regenerates")
    table = carts_table()
    C = Query()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    table.update({"expires_at": past}, C.cart_id == quote.cart_id)
    demoted = get_cart()
    assert demoted.state == CartState.ITEMS_ADDED
    assert demoted.payment_link is None, "lapse should clear payment_link"
    print("OK: lapse cleared payment_link")
    reserve_seats()
    quote3 = generate_payment_link()
    # Link is deterministic on cart_id, so the URL itself is unchanged.
    # The point is the server *did* regenerate it (was None mid-flow).
    assert quote3.payment_link == quote.payment_link
    print("OK: re-reservation regenerated the (deterministic) link")

    _section("17. confirm_booking — success path")
    confirmed = confirm_booking()
    assert confirmed.state == CartState.CONFIRMED
    assert confirmed.booking_id is not None
    assert confirmed.paid_at is not None
    assert confirmed.confirmed_at is not None
    assert confirmed.qr_data_uri is not None
    assert confirmed.qr_data_uri.startswith("data:image/png;base64,")
    assert confirmed.expires_at is None, "expires_at should be cleared on CONFIRMED"
    print(
        f"OK: state={confirmed.state}  booking_id={confirmed.booking_id}  "
        f"qr_bytes_b64_len={len(confirmed.qr_data_uri)}"
    )

    _section("18. after CONFIRMED, no open cart — get_cart should raise")
    try:
        get_cart()
    except ValueError as e:
        print(f"OK: rejected with — {e}")
    else:
        raise AssertionError("expected ValueError reading after confirm")

    _section("19. confirm_booking with no payment_link — should fail")
    # Fresh cart, reserve, then null out the payment_link, then confirm.
    _wipe_user_carts()
    create_cart()
    await add_to_cart(event_id=event.id, quantity=1)
    reserved2 = reserve_seats()
    table.update({"payment_link": None}, C.cart_id == reserved2.cart_id)
    try:
        confirm_booking()
    except ValueError as e:
        print(f"OK: rejected with — {e}")
    else:
        raise AssertionError("expected ValueError confirming without payment_link")


if __name__ == "__main__":
    asyncio.run(main())
