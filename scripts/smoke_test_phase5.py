"""Smoke test: Phase 5 — booking flow.

Grows commit by commit. Right now: just create_cart and its
"return existing open cart" idempotency.

Re-running is safe: every call returns the same open cart (same
cart_id) until something promotes it past CREATED.

Run with:
    uv run python scripts/smoke_test_phase5.py
"""
from __future__ import annotations

from events_mcp.logging import configure_logging
from events_mcp.tools.booking import create_cart


def _section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def main() -> None:
    configure_logging()

    _section("1. create_cart — first call")
    cart = create_cart()
    print(f"cart_id={cart.cart_id}  state={cart.state}  items={len(cart.items)}")

    _section("2. create_cart again — should return same open cart")
    cart2 = create_cart()
    assert cart.cart_id == cart2.cart_id, "expected same open cart back"
    print("OK: same cart_id returned (one open cart per user)")


if __name__ == "__main__":
    main()
