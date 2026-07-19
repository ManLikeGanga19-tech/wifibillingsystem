"""Transactional notifications — the one-off SMS a customer actually wants.

Distinct from campaigns (marketing blasts, in tasks.dispatch_campaign): these are
event-driven receipts and warnings — "you're online", "your time is almost up". They go
out one at a time, triggered by something that happened, and they are what turns a
hotspot from a thing you keep re-buying into a thing that reminds you to.
"""

import logging

from django.db import transaction as db_transaction

from .models import Channel, Message
from .templates import render

logger = logging.getLogger(__name__)

# SMS is billed per 160-character segment. One segment is the ideal for a transactional
# message; an ISP who edits a template longer than that pays for more segments, and the
# console warns them. We hard-cap at 4 segments so a runaway template can't send a novel.
SMS_MAX = 160
SMS_HARD_MAX = 640


# --- operator (team) alerts ------------------------------------------------------------
# These go to the ISP's OWN people — "a router just went down" — not their customers. So
# they skip the notify_customers_sms gate (that's a customer switch) and ride category=ALERT,
# which notifications.tasks.send_message treats as non-billable (the ISP shouldn't pay us to
# be told their kit is offline).


def alert_settings_for(operator):
    from .models import OperatorAlertSettings

    row, _ = OperatorAlertSettings.objects.get_or_create(operator=operator)
    return row


def _operator_admin_phones(operator) -> list[str]:
    """Every number that should hear an operator alert when no explicit list is set: the
    ISP's owner logins plus their contact number. Deduped, digits only."""
    from apps.accounts.models import Role, User

    candidates = list(
        User.objects.filter(operator=operator, role=Role.TENANT_OWNER)
        .exclude(phone="")
        .values_list("phone", flat=True)
    )
    if operator.contact_phone:
        candidates.append(operator.contact_phone)
    seen, out = set(), []
    for raw in candidates:
        p = (raw or "").strip()
        if p.isdigit() and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def send_operator_alert(operator, body: str, *, settings=None) -> int:
    """Text the ISP's team a one-off alert (router up/down). Returns how many were queued.

    Recipients: the explicit alert list if set, else every admin. Channel: WhatsApp when the
    ISP prefers it AND a WhatsApp gateway is actually configured, otherwise SMS — a preference
    for a channel that can't send is silently downgraded rather than dropped."""
    from .models import Channel, MessagingSettings
    from .models import Message as _Message

    conf = settings or alert_settings_for(operator)
    numbers = [str(p) for p in (conf.router_alert_phones or []) if str(p).isdigit()]
    if not numbers:
        numbers = _operator_admin_phones(operator)
    if not numbers:
        return 0

    channel = Channel.SMS
    if conf.prefer_whatsapp:
        ms = MessagingSettings.objects.filter(operator=operator).first()
        if ms and ms.whatsapp_provider:
            channel = Channel.WHATSAPP

    from .tasks import send_message

    queued = 0
    for number in numbers:
        msg = _Message.objects.create(
            operator=operator,
            to_phone=number,
            channel=channel,
            category=_Message.Category.ALERT,
            body=body[:SMS_HARD_MAX],
        )
        db_transaction.on_commit(lambda pk=msg.pk: send_message.delay(pk))
        queued += 1
    return queued


def send_sms(operator, to_phone: str, body: str, *, category=Message.Category.OTHER):
    """Queue one transactional SMS to a customer. Returns the Message, or None if it
    was suppressed (no number, or the ISP switched customer SMS off).

    The actual send goes out on COMMIT — never inside the transaction that triggered
    it. Sending mid-transaction risks an SMS for a payment that then rolls back, which
    is a customer told they're online when they aren't.
    """
    to_phone = (to_phone or "").strip()
    if not to_phone or not to_phone.isdigit():
        return None
    if not getattr(operator, "notify_customers_sms", True):
        return None

    msg = Message.objects.create(
        operator=operator,
        to_phone=to_phone,
        channel=Channel.SMS,
        category=category,
        body=body[:SMS_HARD_MAX],
    )
    from .tasks import send_message

    db_transaction.on_commit(lambda: send_message.delay(msg.pk))
    return msg


def _session_phone(session) -> str:
    """The customer's number for a session. Hotspot logins use the phone AS the
    username; vouchers use the code, so fall back to the subscriber."""
    username = session.hotspot_username or ""
    if username.isdigit():
        return username
    subscriber = getattr(session, "subscriber", None)
    return subscriber.phone if subscriber else ""


# --- context helpers: build the variables the templates substitute --------------------


def _company_name(operator) -> str:
    branding = getattr(operator, "branding", None)
    return (branding.name_for_customers if branding else "") or operator.name


def _first_name(full_name: str) -> str:
    return (full_name or "").strip().split(" ")[0]


def _platform_paybill() -> str:
    """The paybill customers pay to. PPPoE account numbers are BillRefs on Danamo's shared
    C2B shortcode, so that is the number in the message."""
    from django.conf import settings

    return settings.DARAJA_SHORTCODE or ""


def _fmt_dt(dt) -> str:
    from django.utils import timezone

    return timezone.localtime(dt).strftime("%d %b %H:%M") if dt else ""


def _fmt_date(d) -> str:
    return d.strftime("%d %b %Y") if d else ""


def _humanize_until(dt) -> str:
    """Human time from now to `dt`: '2 days', '5 hours', 'a few minutes'."""
    from django.utils import timezone

    if not dt:
        return ""
    secs = int((dt - timezone.now()).total_seconds())
    if secs <= 0:
        return "now"
    if secs >= 86400:
        n = secs // 86400
        return f"{n} day{'s' if n > 1 else ''}"
    if secs >= 3600:
        n = secs // 3600
        return f"{n} hour{'s' if n > 1 else ''}"
    mins = secs // 60
    return f"{mins} minutes" if mins >= 5 else "a few minutes"


def _humanize_days(date_) -> str:
    """Whole days from today to a date: '3 days', 'today'."""
    from django.utils import timezone

    if not date_:
        return ""
    days = (date_ - timezone.localdate()).days
    if days <= 0:
        return "today"
    return f"{days} day{'s' if days > 1 else ''}"


def _fmt_duration(td) -> str:
    """A plan's DurationField as friendly text: '1 hour', '1 day', '1 week', '30 days'."""
    secs = int(td.total_seconds())
    for unit, size in (("week", 604800), ("day", 86400), ("hour", 3600)):
        if secs >= size and secs % size == 0:
            n = secs // size
            return f"{n} {unit}{'s' if n > 1 else ''}"
    mins = max(1, secs // 60)
    return f"{mins} minutes"


def _fmt_mb(mb: int) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{int(mb)} MB"


# --- hotspot ---------------------------------------------------------------------------


def notify_online(session):
    """"You're connected." Sent when a paid hotspot session goes active — the receipt."""
    phone = _session_phone(session)
    if not phone:
        return
    op = session.operator
    tx = getattr(session, "transaction", None)
    body = render(op, "hotspot_online", {
        "company_name": _company_name(op),
        "package_name": session.plan.name,
        "expiry_date": _fmt_dt(session.expires_at),
        "amount": f"{tx.amount:.0f}" if tx else "",
        "days_left": _humanize_until(session.expires_at),
        "first_name": _first_name(getattr(getattr(session, "subscriber", None), "name", "")),
    })
    if body:
        send_sms(op, phone, body, category=Message.Category.PAYMENT)


def notify_data_low(session):
    """"You're nearly out of data." Fires once on a capped hotspot plan near the limit."""
    phone = _session_phone(session)
    if not phone:
        return
    op = session.operator
    cap = session.plan.data_cap_mb or 0
    used = session.data_used_mb or 0
    body = render(op, "hotspot_data_low", {
        "first_name": _first_name(getattr(getattr(session, "subscriber", None), "name", "")),
        "bundle_percentage_used": str(round(100 * used / cap)) if cap else "",
        "bundle_data_remaining": _fmt_mb(max(0, cap - used)) if cap else "",
        "package_name": session.plan.name,
        "company_name": _company_name(op),
    })
    if body:
        send_sms(op, phone, body, category=Message.Category.EXPIRY)


def notify_expiring(session):
    """"Your time is almost up." The renewal nudge a few minutes before a session ends."""
    phone = _session_phone(session)
    if not phone:
        return
    op = session.operator
    body = render(op, "hotspot_expiring", {
        "company_name": _company_name(op),
        "package_name": session.plan.name,
        "days_left": _humanize_until(session.expires_at),
        "expiry_date": _fmt_dt(session.expires_at),
        "first_name": _first_name(getattr(getattr(session, "subscriber", None), "name", "")),
    })
    if body:
        send_sms(op, phone, body, category=Message.Category.EXPIRY)


# --- PPPoE (fixed-line) ----------------------------------------------------------------


def _pppoe_ctx(client) -> dict:
    op = client.operator
    return {
        "first_name": _first_name(client.full_name),
        "username": client.pppoe_username,
        "password": client.pppoe_password,
        "package_name": client.plan.name,
        "expiry_date": _fmt_date(client.next_due_date),
        "days_left": _humanize_days(client.next_due_date),
        "amount": f"{client.plan.price:.0f}",
        "account_number": client.account_number,
        "paybill": _platform_paybill(),
        "company_name": _company_name(op),
    }


def notify_pppoe_welcome(client):
    """Welcome + login details, sent when a fixed-line client is created."""
    if not client.phone:
        return
    body = render(client.operator, "pppoe_welcome", _pppoe_ctx(client))
    if body:
        send_sms(client.operator, client.phone, body, category=Message.Category.PPPOE)


def notify_pppoe_expiring(client):
    """Renewal reminder before a fixed-line subscription falls due."""
    if not client.phone:
        return
    body = render(client.operator, "pppoe_expiring", _pppoe_ctx(client))
    if body:
        send_sms(client.operator, client.phone, body, category=Message.Category.PPPOE)


def notify_pppoe_expired(client):
    """Sent when a fixed-line client is suspended for non-payment."""
    if not client.phone:
        return
    body = render(client.operator, "pppoe_expired", _pppoe_ctx(client))
    if body:
        send_sms(client.operator, client.phone, body, category=Message.Category.PPPOE)


def notify_pppoe_data_low(client, *, percent_used: int, remaining_mb: int):
    """Fair-use (FUP) warning when a fixed-line client nears their data threshold."""
    if not client.phone:
        return
    op = client.operator
    body = render(op, "pppoe_data_low", {
        "first_name": _first_name(client.full_name),
        "username": client.pppoe_username,
        "bundle_percentage_used": str(percent_used),
        "bundle_data_remaining": _fmt_mb(max(0, remaining_mb)),
        "package_name": client.plan.name,
        "company_name": _company_name(op),
    })
    if body:
        send_sms(op, client.phone, body, category=Message.Category.PPPOE)


# --- voucher ---------------------------------------------------------------------------


def notify_voucher(voucher, phone: str) -> bool:
    """Text a prepaid voucher code to a customer. Returns True if a message was queued."""
    op = voucher.operator
    body = render(op, "voucher_issued", {
        "code": voucher.code,
        "package_name": voucher.plan.name,
        "duration": _fmt_duration(voucher.plan.duration),
        "amount": f"{voucher.plan.price:.0f}",
        "company_name": _company_name(op),
    })
    if body:
        return send_sms(op, phone, body, category=Message.Category.PAYMENT) is not None
    return False
