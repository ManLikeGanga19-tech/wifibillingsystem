import logging
from decimal import Decimal

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_message(self, message_id: int):
    from apps.billing import platform_account

    from .models import Channel, Message
    from .providers import get_provider, is_managed_sms

    msg = Message.objects.get(pk=message_id)
    if msg.status == Message.Status.SENT:
        return

    # Billable = it leaves on OUR gateway (we pay the bill), it is an SMS, and it serves
    # the ISP's customers rather than us. A low-balance warning is exempt: charging for the
    # message that tells them they cannot afford to send messages would be self-defeating,
    # and it is the one message that must always get through.
    metered = (
        msg.channel == Channel.SMS
        and is_managed_sms(msg.operator)
        and msg.category not in Message.NON_BILLABLE
    )

    # Prepaid, so check BEFORE sending: a negative balance would mean we hand the gateway
    # money the ISP never gave us. Fail outright rather than retry — retrying cannot
    # conjure credit, and a task waking up for three days is noise, not resilience.
    if metered and not platform_account.can_send_sms(msg.operator):
        msg.status = Message.Status.FAILED
        msg.error = "Out of SMS balance. Top up in Settings > Communications."
        msg.save()
        logger.warning("Operator %s has no SMS balance", msg.operator_id)
        _tally_campaign(msg)
        return

    # The operator decides whose gateway this leaves on — their own, or the platform's.
    result = get_provider(msg.channel, msg.operator).send(msg)
    if result.ok:
        msg.status = Message.Status.SENT
        msg.provider_ref = result.provider_ref
        msg.sent_at = timezone.now()
        msg.error = ""
        # Charge only for a message that actually went out, and only once however many
        # times this task retried (the charge is unique per message).
        if metered:
            platform_account.charge_sms(msg.operator, msg, segments=_segments(msg.body))
    else:
        # Final state only after retries exhaust
        if self.request.retries >= self.max_retries:
            msg.status = Message.Status.FAILED
        msg.error = result.error[:255]
    msg.save()
    _tally_campaign(msg)
    if not result.ok and self.request.retries < self.max_retries:
        raise RuntimeError(f"Send failed, retrying: {result.error}")


#: An SMS is billed per 160-character segment; a longer body is several messages, and the
#: gateway charges for each. Concatenated parts carry a header, so they hold 153.
SMS_SEGMENT = 160
SMS_CONCAT_SEGMENT = 153


def _segments(body: str) -> int:
    length = len(body or "")
    if length <= SMS_SEGMENT:
        return 1
    return -(-length // SMS_CONCAT_SEGMENT)  # ceiling division


def _tally_campaign(msg) -> None:
    from .models import Campaign, Message

    if not msg.campaign_id or msg.status == Message.Status.QUEUED:
        return
    field = "sent_count" if msg.status == Message.Status.SENT else "failed_count"
    Campaign.objects.filter(pk=msg.campaign_id).update(**{field: F(field) + 1})
    campaign = Campaign.objects.get(pk=msg.campaign_id)
    if campaign.sent_count + campaign.failed_count >= campaign.total_recipients:
        campaign.status = Campaign.Status.DONE
        campaign.save(update_fields=["status", "updated_at"])


@shared_task
def dispatch_campaign(campaign_id: int):
    """Resolve the audience into Message rows and queue individual sends."""
    from apps.accounts.models import Subscriber
    from apps.provisioning.models import Session

    from .models import Campaign, Channel, Message

    campaign = Campaign.objects.get(pk=campaign_id)
    customers = Subscriber.objects.filter(operator=campaign.operator, is_blocked=False)
    if campaign.channel == Channel.EMAIL:
        customers = customers.exclude(email="")
    else:
        customers = customers.exclude(phone="")
    if campaign.audience == Campaign.Audience.ACTIVE:
        customers = customers.filter(sessions__status=Session.Status.ACTIVE)
    elif campaign.audience == Campaign.Audience.EXPIRED:
        customers = customers.filter(sessions__isnull=False).exclude(
            sessions__status=Session.Status.ACTIVE
        )
    is_email = campaign.channel == Channel.EMAIL
    field = "email" if is_email else "phone"
    # Pull the name too, so @first_name fills per recipient. distinct() on (contact, name)
    # still collapses a subscriber the audience join duplicated.
    recipients = list(customers.values_list(field, "name").distinct())

    from .services import _company_name, _first_name, personalize_campaign

    company = _company_name(campaign.operator)

    def _body(name: str) -> str:
        return personalize_campaign(
            campaign.body, first_name=_first_name(name), company_name=company
        )

    messages = Message.objects.bulk_create(
        Message(
            operator=campaign.operator,
            campaign=campaign,
            to_phone="" if is_email else contact,
            to_email=contact if is_email else "",
            channel=campaign.channel,
            subject=campaign.subject,
            body=_body(name),
        )
        for contact, name in recipients
    )
    campaign.total_recipients = len(messages)
    campaign.status = (
        Campaign.Status.SENDING if messages else Campaign.Status.DONE
    )
    campaign.save(update_fields=["total_recipients", "status", "updated_at"])
    for msg in messages:
        send_message.delay(msg.pk)
    logger.info("Campaign %s dispatched to %d recipients", campaign.pk, len(messages))
    return len(messages)


@shared_task
def warn_low_platform_balance():
    """Tell an ISP their SMS balance is running out — BEFORE their receipts stop.

    The whole point of the managed gateway is that messaging just works. A balance that
    quietly hits zero breaks that promise in the worst way: the ISP finds out when a
    customer says they never got their code.

    Two rules keep this useful rather than annoying:
      * we warn ONCE per fall, not every hour (low_balance_alerted_at), and the flag is
        cleared when they top back up, so the next fall warns again;
      * the warning itself is NOT billed to them (category=ALERT). Charging for the message
        that says "you cannot afford to send messages" would be absurd, and at a zero
        balance it could not be sent at all — which is precisely when it matters most.
    """
    from django.utils import timezone

    from apps.billing import platform_account

    from .models import MessagingSettings
    from .services import send_sms

    warned = 0
    for config in MessagingSettings.objects.select_related("operator"):
        operator = config.operator
        balance = platform_account.balance(operator)

        if balance > config.low_balance_threshold:
            # Recovered — arm the alarm again for the next fall.
            if config.low_balance_alerted_at:
                config.low_balance_alerted_at = None
                config.save(update_fields=["low_balance_alerted_at", "updated_at"])
            continue

        if config.low_balance_alerted_at:
            continue  # already told them about this fall

        numbers = config.alert_phones or []
        if not numbers and operator.contact_phone:
            numbers = [operator.contact_phone]  # better than warning nobody
        if not numbers:
            continue

        sms_left = max(int(balance / platform_account.SMS_PRICE), 0) if balance > 0 else 0
        body = (
            f"WIFI.OS: your SMS balance is KSh {balance:,.0f} (about {sms_left} messages). "
            "Top up in Settings > Communications, or your customers will stop getting "
            "receipts."
        )
        from .models import Message

        for number in numbers:
            send_sms(operator, number, body, category=Message.Category.ALERT)

        config.low_balance_alerted_at = timezone.now()
        config.save(update_fields=["low_balance_alerted_at", "updated_at"])
        warned += 1

    return warned


def _digest_recipients(operator) -> list[str]:
    """Who a sales digest emails: the ISP's owner login(s) and their contact address, deduped.
    The login address is the durable one; contact_email is a nice-to-have they can edit."""
    from apps.accounts.models import Role

    emails = list(
        operator.users.filter(role=Role.TENANT_OWNER)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if operator.contact_email:
        emails.append(operator.contact_email)
    seen, out = set(), []
    for e in emails:
        e = (e or "").strip()
        if e and e.lower() not in seen:
            seen.add(e.lower())
            out.append(e)
    return out


@shared_task
def send_sales_digests():
    """Daily: email each opted-in ISP yesterday's takings, so the team can see the day without
    logging in (Settings > Operator alerts). Reads the SALE ledger — the same gross figure the
    dashboard shows — so the email and the console never disagree."""
    from datetime import datetime, time, timedelta

    from django.conf import settings as dj_settings
    from django.core.mail import send_mail
    from django.db.models import Count, Sum
    from django.db.models.functions import Coalesce

    from apps.billing.models import LedgerEntry

    from .models import OperatorAlertSettings

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    start = timezone.make_aware(datetime.combine(yesterday, time.min))
    end = timezone.make_aware(datetime.combine(today, time.min))
    from_email = getattr(dj_settings, "DEFAULT_FROM_EMAIL", "noreply@wifios.co.ke")
    label = yesterday.strftime("%a %d %b %Y")

    sent = 0
    for conf in OperatorAlertSettings.objects.filter(sales_digest_enabled=True).select_related(
        "operator"
    ):
        operator = conf.operator
        recipients = _digest_recipients(operator)
        if not recipients:
            continue

        agg = LedgerEntry.objects.filter(
            operator=operator,
            entry_type=LedgerEntry.Type.SALE,
            created_at__gte=start,
            created_at__lt=end,
        ).aggregate(
            gross=Coalesce(Sum("amount"), Decimal("0")),
            payments=Count("id"),
        )
        gross, payments = agg["gross"], agg["payments"]

        if payments:
            headline = f"KES {gross:,.0f} from {payments} payment{'s' if payments != 1 else ''}"
        else:
            headline = "No payments"
        body = (
            f"Hi,\n\n"
            f"{operator.name} — sales for {label}:\n\n"
            f"    {headline}\n\n"
            "See the full breakdown in your console under Reports.\n\n"
            "You're getting this because the daily sales digest is on in "
            "Settings > Operator alerts.\n\n"
            "— WIFI.OS"
        )
        try:
            send_mail(
                f"{operator.name}: sales for {label} — KES {gross:,.0f}",
                body, from_email, recipients, fail_silently=False,
            )
            sent += 1
        except Exception:
            logger.exception("Could not send the sales digest for %s", operator.slug)

    return sent
