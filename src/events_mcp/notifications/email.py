"""Resend email integration for booking confirmations.

Best-effort: any failure path is captured as a ``skipped_reason`` string
and the caller (``confirm_booking``) treats the booking as CONFIRMED
regardless. The cart is already saved on disk before this module runs.

Privacy contract:
- The recipient email value is NEVER written to logs. Logs reference
  ``user_id`` and ``cart_id`` / ``booking_id`` only.
- The email flows: ``preferences -> Resend payload -> Resend's servers``.
  No copy of it lives outside that path.
"""
from __future__ import annotations

import html as html_lib

import httpx
import resend
from resend.exceptions import ResendError

from events_mcp.config import get_settings
from events_mcp.logging import get_logger
from events_mcp.models.cart import CalendarLink, Cart, CartItem
from events_mcp.models.events import EventDetail
from events_mcp.notifications.calendar import ICSEventInput, build_ics_text
from events_mcp.storage.db import DEFAULT_USER_ID
from events_mcp.tools.favorites import get_preferences

log = get_logger(__name__)


async def send_booking_confirmation(
    *,
    cart: Cart,
    booking_id: str,
    event_details_by_id: dict[str, EventDetail],
    calendar_links: list[CalendarLink],
) -> tuple[bool, str | None]:
    """Send a booking confirmation email via Resend.

    Returns ``(sent, skipped_reason)``. Never raises — every failure
    path yields a stable reason string suitable for surfacing in
    ``BookingConfirmation.email_skipped_reason``.

    Skip reasons:
    - ``"resend_not_configured"`` — RESEND_API_KEY not set in env.
    - ``"no_email_in_preferences"`` — user never called set_preferences(email=...).
    - ``"resend_api_error"`` — Resend rejected the request (auth, rate
      limit, validation). Status code is logged; address is not.
    - ``"network_error"`` — httpx-level transport failure.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        log.info(
            "email_skipped",
            user_id=DEFAULT_USER_ID,
            cart_id=cart.cart_id,
            reason="resend_not_configured",
        )
        return False, "resend_not_configured"

    prefs = get_preferences()
    if not prefs.email:
        log.info(
            "email_skipped",
            user_id=DEFAULT_USER_ID,
            cart_id=cart.cart_id,
            reason="no_email_in_preferences",
        )
        return False, "no_email_in_preferences"

    subject = f"Your booking is confirmed (#{booking_id[:8]})"
    html_body = _render_html(cart, booking_id, event_details_by_id, calendar_links)
    ics_text = build_ics_text(
        _to_ics_inputs(cart, booking_id, event_details_by_id)
    )

    resend.api_key = settings.resend_api_key
    params: resend.Emails.SendParams = {
        "from": settings.resend_from,
        "to": [prefs.email],
        "subject": subject,
        "html": html_body,
        "attachments": [
            {
                "filename": "booking.ics",
                "content": list(ics_text.encode("utf-8")),
                "content_type": "text/calendar; charset=utf-8",
            }
        ],
    }

    try:
        result = await resend.Emails.send_async(params)
    except ResendError as e:
        log.warning(
            "email_failed",
            user_id=DEFAULT_USER_ID,
            cart_id=cart.cart_id,
            reason="resend_api_error",
            error_class=type(e).__name__,
            status_code=getattr(e, "code", None),
        )
        return False, "resend_api_error"
    except httpx.HTTPError as e:
        log.warning(
            "email_failed",
            user_id=DEFAULT_USER_ID,
            cart_id=cart.cart_id,
            reason="network_error",
            error_class=type(e).__name__,
        )
        return False, "network_error"

    resend_id = result.get("id") if isinstance(result, dict) else None
    log.info(
        "email_sent",
        user_id=DEFAULT_USER_ID,
        cart_id=cart.cart_id,
        booking_id=booking_id,
        resend_id=resend_id,
    )
    return True, None


def _to_ics_inputs(
    cart: Cart,
    booking_id: str,
    event_details_by_id: dict[str, EventDetail],
) -> list[ICSEventInput]:
    """Build one ICSEventInput per unique event for which we have details."""
    inputs: list[ICSEventInput] = []
    seen: set[str] = set()
    for item in cart.items:
        if item.event_id in seen:
            continue
        seen.add(item.event_id)

        detail = event_details_by_id.get(item.event_id)
        if detail is None:
            continue

        location_parts = [p for p in (detail.venue_name, detail.city) if p]
        location = ", ".join(location_parts) if location_parts else None

        inputs.append(
            ICSEventInput(
                uid=f"{booking_id}:{item.event_id}@events-mcp",
                title=detail.name,
                start_date=detail.start_date,
                start_time=detail.start_time,
                timezone=detail.timezone,
                location=location,
                description=(
                    f"Booking {booking_id} via Events MCP. "
                    f"Tickets: {item.quantity}."
                ),
            )
        )
    return inputs


def _render_html(
    cart: Cart,
    booking_id: str,
    event_details_by_id: dict[str, EventDetail],
    calendar_links: list[CalendarLink],
) -> str:
    """Compose the HTML email body. Every interpolated string is escaped."""
    cal_url_by_event_id = {link.event_id: link.url for link in calendar_links}

    rows: list[str] = []
    seen: set[str] = set()
    for item in cart.items:
        if item.event_id in seen:
            continue
        seen.add(item.event_id)
        rows.append(
            _render_event_row(
                item,
                event_details_by_id.get(item.event_id),
                cal_url_by_event_id.get(item.event_id),
            )
        )

    total, currency = _compute_total(cart.items)
    total_line = (
        f"{currency} {total:.2f}" if currency else f"{total:.2f}"
    )

    qr_block = ""
    if cart.qr_data_uri:
        qr_block = (
            '<div style="margin-top:24px;text-align:center;">'
            '<p style="margin:0 0 8px;color:#555;font-size:13px;">'
            "Show this QR at the venue:</p>"
            f'<img src="{html_lib.escape(cart.qr_data_uri)}" '
            'alt="Booking QR code" width="180" height="180" '
            'style="border:1px solid #eee;border-radius:8px;">'
            "</div>"
        )

    return f"""<!doctype html>
<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;
                  background:#f6f6f6;margin:0;padding:24px;color:#222;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;
              padding:32px;box-shadow:0 1px 3px rgba(0,0,0,0.05);">
    <h1 style="margin:0 0 8px;font-size:22px;">Your booking is confirmed</h1>
    <p style="margin:0 0 24px;color:#555;font-size:14px;">
      Booking ID <code>{html_lib.escape(booking_id)}</code>
    </p>

    {''.join(rows)}

    <div style="margin-top:24px;padding-top:16px;border-top:1px solid #eee;
                display:flex;justify-content:space-between;font-weight:600;">
      <span>Total</span>
      <span>{html_lib.escape(total_line)}</span>
    </div>

    {qr_block}

    <p style="margin-top:24px;color:#888;font-size:12px;">
      A <code>booking.ics</code> calendar file is attached — open it in
      your calendar app to add the event(s).
    </p>
    <p style="margin-top:8px;color:#aaa;font-size:11px;">
      Events MCP — simulated booking. No real payment was charged.
    </p>
  </div>
</body></html>"""


def _render_event_row(
    item: CartItem,
    detail: EventDetail | None,
    calendar_url: str | None,
) -> str:
    name = html_lib.escape(item.event_name)
    qty = item.quantity

    when = ""
    where = ""
    if detail is not None:
        if detail.start_date:
            date_bits = [detail.start_date]
            if detail.start_time:
                date_bits.append(detail.start_time)
            when = (
                '<div style="color:#555;font-size:13px;margin-top:2px;">'
                f"{html_lib.escape(' · '.join(date_bits))}</div>"
            )
        venue_parts = [p for p in (detail.venue_name, detail.city) if p]
        if venue_parts:
            where = (
                '<div style="color:#555;font-size:13px;">'
                f"{html_lib.escape(', '.join(venue_parts))}</div>"
            )

    price_line = ""
    if item.unit_price is not None:
        line_total = item.unit_price * qty
        cur = item.currency or ""
        price_line = (
            '<div style="color:#888;font-size:12px;margin-top:6px;">'
            f"{qty} × {item.unit_price:.2f} {html_lib.escape(cur)} = "
            f"{line_total:.2f} {html_lib.escape(cur)}</div>"
        )
    else:
        price_line = (
            '<div style="color:#888;font-size:12px;margin-top:6px;">'
            f"{qty} ticket(s) — price not listed</div>"
        )

    cal_link = ""
    if calendar_url:
        cal_link = (
            '<div style="margin-top:8px;">'
            f'<a href="{html_lib.escape(calendar_url)}" '
            'style="color:#1a73e8;font-size:13px;text-decoration:none;">'
            "+ Add to Google Calendar</a></div>"
        )

    return (
        '<div style="padding:16px 0;border-top:1px solid #eee;">'
        f'<div style="font-weight:600;font-size:15px;">{name}</div>'
        f"{when}{where}{price_line}{cal_link}"
        "</div>"
    )


def _compute_total(items: list[CartItem]) -> tuple[float, str | None]:
    """Mirror booking._compute_total but return only the (total, currency) pair."""
    total = 0.0
    currency: str | None = None
    for item in items:
        if item.unit_price is None:
            continue
        total += item.unit_price * item.quantity
        if currency is None:
            currency = item.currency
    return total, currency
