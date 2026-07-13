import logging

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_message(self, message_id: int):
    from . import credits
    from .models import Channel, Message
    from .providers import get_provider, is_managed_sms

    msg = Message.objects.get(pk=message_id)
    if msg.status == Message.Status.SENT:
        return

    # The managed gateway is prepaid. Check BEFORE sending — running an ISP's balance
    # negative would mean we hand Africa's Talking money they never gave us. Fail this
    # message outright rather than retry: retrying cannot conjure credit, and a task that
    # keeps waking up for three days is noise, not resilience.
    metered = msg.channel == Channel.SMS and is_managed_sms(msg.operator)
    if metered and not credits.has_credit(msg.operator):
        msg.status = Message.Status.FAILED
        msg.error = "Out of SMS credits. Top up in Settings > Communications."
        msg.save()
        logger.warning("Operator %s is out of SMS credits", msg.operator_id)
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
        # times this task retried (the debit is unique per message).
        if metered:
            credits.consume(msg.operator, msg, segments=_segments(msg.body))
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
    field = "email" if campaign.channel == Channel.EMAIL else "phone"
    recipients = list(customers.values_list(field, flat=True).distinct())

    messages = Message.objects.bulk_create(
        Message(
            operator=campaign.operator,
            campaign=campaign,
            to_phone="" if campaign.channel == Channel.EMAIL else recipient,
            to_email=recipient if campaign.channel == Channel.EMAIL else "",
            channel=campaign.channel,
            subject=campaign.subject,
            body=campaign.body,
        )
        for recipient in recipients
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
