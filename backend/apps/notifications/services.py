"""Transactional notifications — the one-off SMS a customer actually wants.

Distinct from campaigns (marketing blasts, in tasks.dispatch_campaign): these are
event-driven receipts and warnings — "you're online", "your time is almost up". They go
out one at a time, triggered by something that happened, and they are what turns a
hotspot from a thing you keep re-buying into a thing that reminds you to.
"""

import logging

from django.db import transaction as db_transaction

from .models import Channel, Message

logger = logging.getLogger(__name__)

# SMS is billed per 160-character segment, so keep transactional copy inside one.
SMS_MAX = 160


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
        body=body[:SMS_MAX],
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


def notify_online(session):
    """"You're connected." Sent when a paid session goes active — the receipt that
    tells a customer their money worked, with when it runs out so they can plan."""
    from django.utils import timezone

    phone = _session_phone(session)
    if not phone:
        return
    expiry = timezone.localtime(session.expires_at).strftime("%d %b %H:%M")
    isp = session.operator.name
    send_sms(
        session.operator,
        phone,
        f"You're online with {isp}. Your {session.plan.name} is active until {expiry}. "
        "Enjoy!",
        category=Message.Category.PAYMENT,
    )


def notify_data_low(session):
    """"You're nearly out of data." Only fires on a capped plan, once, near the limit —
    the same renewal nudge as expiry, for the customers whose plan runs out by bytes
    rather than by clock."""
    phone = _session_phone(session)
    if not phone:
        return
    isp = session.operator.name
    send_sms(
        session.operator,
        phone,
        f"You've nearly used up the data on your {isp} {session.plan.name}. "
        "Reconnect and pay to keep browsing.",
        category=Message.Category.EXPIRY,
    )


def notify_expiring(session):
    """"Your time is almost up." The renewal nudge — the whole reason a hotspot keeps
    earning instead of silently dropping people offline."""
    phone = _session_phone(session)
    if not phone:
        return
    isp = session.operator.name
    send_sms(
        session.operator,
        phone,
        f"Your {isp} WiFi ({session.plan.name}) runs out in a few minutes. "
        "Reconnect and pay to stay online.",
        category=Message.Category.EXPIRY,
    )
