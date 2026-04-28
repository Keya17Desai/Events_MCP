"""Smoke test: Phase 5.5 commit 3/3 — Resend email integration.

Exercises the three branches of ``send_booking_confirmation``:

1. RESEND_API_KEY unset       → skipped with reason='resend_not_configured'
2. RESEND_API_KEY set,         → skipped with reason='no_email_in_preferences'
   no email in preferences
3. Both set + valid Resend key → real send (gated on the test env vars
                                  being set, otherwise printed skipped)

The test fabricates an in-memory Cart + EventDetail map so it does NOT
depend on a Ticketmaster call or on Phase 5 wiring. We monkey-patch
RESEND_API_KEY into ``os.environ`` and bust the ``get_settings()``
lru_cache so each scenario sees fresh config.

Run with:
    uv run python scripts/smoke_test_email.py

To exercise the real-send branch, set both:
    RESEND_API_KEY=re_xxxx EVENTS_MCP_TEST_EMAIL=you@example.com \\
        uv run python scripts/smoke_test_email.py
"""
from __future__ import annotations

import asyncio
import os

from events_mcp.config import get_settings
from events_mcp.logging import configure_logging
from events_mcp.models.cart import CalendarLink, Cart, CartItem, CartState
from events_mcp.models.events import EventDetail
from events_mcp.notifications.email import send_booking_confirmation
from events_mcp.storage.db import DEFAULT_USER_ID, preferences_table
from events_mcp.tools.favorites import set_preferences


def _section(title: str) -> None:
    print(f"\n{'─' * 60}\n  {title}\n{'─' * 60}")


def _wipe_preferences() -> None:
    preferences_table().truncate()


def _fixture_cart_and_details() -> tuple[Cart, dict[str, EventDetail]]:
    """A two-event cart with full details, no Ticketmaster call needed."""
    cart = Cart(
        cart_id="cart-test-1",
        user_id=DEFAULT_USER_ID,
        state=CartState.CONFIRMED,
        items=[
            CartItem(
                event_id="evt-1",
                event_name="Coldplay — Music of the Spheres",
                quantity=2,
                unit_price=125.0,
                currency="USD",
            ),
            CartItem(
                event_id="evt-2",
                event_name="Met Museum — Surrealism Exhibit",
                quantity=1,
                unit_price=30.0,
                currency="USD",
            ),
        ],
        created_at="2026-04-28T16:00:00+00:00",
        updated_at="2026-04-28T16:05:00+00:00",
        payment_link="https://payments.events-mcp.local/pay/cart-test-1",
        paid_at="2026-04-28T16:05:00+00:00",
        booking_id="booking-test-abc",
        confirmed_at="2026-04-28T16:05:00+00:00",
        # Tiny 1×1 transparent PNG so we can confirm the inline-img path
        # renders without bloating the test fixture.
        qr_data_uri=(
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII="
        ),
    )
    details = {
        "evt-1": EventDetail(
            id="evt-1",
            name="Coldplay — Music of the Spheres",
            start_date="2026-05-15",
            start_time="19:30:00",
            timezone="America/New_York",
            venue_name="Madison Square Garden",
            city="New York",
        ),
        "evt-2": EventDetail(
            id="evt-2",
            name="Met Museum — Surrealism Exhibit",
            start_date="2026-05-16",
            start_time=None,
            timezone=None,
            venue_name="The Met",
            city="New York",
        ),
    }
    return cart, details


def _calendar_links_for(cart: Cart) -> list[CalendarLink]:
    """Stub calendar links — content doesn't matter for the email test."""
    return [
        CalendarLink(
            event_id=item.event_id,
            event_name=item.event_name,
            url=f"https://calendar.google.com/calendar/r/eventedit?text={item.event_id}",
        )
        for item in cart.items
    ]


def _bust_settings_cache() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]


async def main() -> None:
    configure_logging()
    cart, details = _fixture_cart_and_details()
    cal_links = _calendar_links_for(cart)

    _section("0. _render_html — direct call exercises template + escaping")
    from events_mcp.notifications.email import _render_html, _to_ics_inputs
    from events_mcp.notifications.calendar import build_ics_text

    html_body = _render_html(cart, "booking-test-abc", details, cal_links)
    assert "<!doctype html>" in html_body
    assert "Your booking is confirmed" in html_body
    assert "booking-test-abc" in html_body
    # Both event names rendered
    assert "Coldplay" in html_body
    assert "Met Museum" in html_body
    # Currency + total ($125 × 2 + $30 = $280)
    assert "USD 280.00" in html_body, "expected total of 280 USD"
    # Inline QR rendered as <img src="data:image/png;base64,...">
    assert 'src="data:image/png;base64,' in html_body
    # Calendar links from stubs
    assert "+ Add to Google Calendar" in html_body
    print(
        f"OK: HTML rendered ({len(html_body)} bytes), "
        f"contains all expected blocks"
    )

    ics_text = build_ics_text(_to_ics_inputs(cart, "booking-test-abc", details))
    assert ics_text.count("BEGIN:VEVENT") == 2
    assert "UID:booking-test-abc:evt-1@events-mcp" in ics_text
    print(f"OK: .ics attachment built ({len(ics_text)} bytes, 2 VEVENTs)")

    _section("1. RESEND_API_KEY unset → skipped: resend_not_configured")
    _wipe_preferences()
    os.environ.pop("RESEND_API_KEY", None)
    _bust_settings_cache()

    sent, reason = await send_booking_confirmation(
        cart=cart,
        booking_id="booking-test-abc",
        event_details_by_id=details,
        calendar_links=cal_links,
    )
    assert sent is False, "should not send without an API key"
    assert reason == "resend_not_configured", reason
    print(f"OK: sent={sent} reason={reason!r}")

    _section("2. Key set + no email in prefs → skipped: no_email_in_preferences")
    _wipe_preferences()  # ensure no email
    os.environ["RESEND_API_KEY"] = "re_fake_key_for_branch_test"
    _bust_settings_cache()

    sent, reason = await send_booking_confirmation(
        cart=cart,
        booking_id="booking-test-abc",
        event_details_by_id=details,
        calendar_links=cal_links,
    )
    assert sent is False, "should not send without an email in preferences"
    assert reason == "no_email_in_preferences", reason
    print(f"OK: sent={sent} reason={reason!r}")

    _section("3. Real send (gated on RESEND_API_KEY + EVENTS_MCP_TEST_EMAIL)")
    real_key = os.environ.get("EVENTS_MCP_REAL_RESEND_API_KEY")
    test_email = os.environ.get("EVENTS_MCP_TEST_EMAIL")

    if not real_key or not test_email:
        print(
            "skipped: set EVENTS_MCP_REAL_RESEND_API_KEY and "
            "EVENTS_MCP_TEST_EMAIL to enable a live send."
        )
        return

    _wipe_preferences()
    set_preferences(email=test_email)
    os.environ["RESEND_API_KEY"] = real_key
    _bust_settings_cache()

    sent, reason = await send_booking_confirmation(
        cart=cart,
        booking_id="booking-test-abc",
        event_details_by_id=details,
        calendar_links=cal_links,
    )
    if sent:
        print(f"OK: sent=True reason={reason!r} — check your inbox")
    else:
        # Don't assert — we want the script to surface the reason for
        # debugging (e.g. invalid key, rate limit) without failing
        # other branches.
        print(f"SEND FAILED: reason={reason!r} — verify Resend key and sender")


if __name__ == "__main__":
    asyncio.run(main())
