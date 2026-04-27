"""Smoke test: Phase 5 — booking flow.

Grows commit by commit. Right now: create_cart, get_cart, add_to_cart
(including merge-on-duplicate behavior).

The test wipes the user's carts at the start so it's safely re-runnable.
We use the storage table directly for cleanup since Phase 5 deliberately
doesn't expose a cancel/delete cart tool.

Run with:
    uv run python scripts/smoke_test_phase5.py
"""
from __future__ import annotations

import asyncio

from tinydb import Query

from events_mcp.logging import configure_logging
from events_mcp.models.cart import CartState
from events_mcp.storage.db import DEFAULT_USER_ID, carts_table
from events_mcp.tools.booking import add_to_cart, create_cart, get_cart
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


if __name__ == "__main__":
    asyncio.run(main())
