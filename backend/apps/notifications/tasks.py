import logging

from celery import shared_task
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_message(self, message_id: int):
    from .models import Campaign, Message
    from .providers import get_provider

    msg = Message.objects.get(pk=message_id)
    if msg.status == Message.Status.SENT:
        return
    result = get_provider(msg.channel).send(msg.to_phone, msg.body)
    if result.ok:
        msg.status = Message.Status.SENT
        msg.provider_ref = result.provider_ref
        msg.sent_at = timezone.now()
        msg.error = ""
    else:
        # Final state only after retries exhaust
        if self.request.retries >= self.max_retries:
            msg.status = Message.Status.FAILED
        msg.error = result.error[:255]
    msg.save()
    if msg.campaign_id and msg.status != Message.Status.QUEUED:
        field = "sent_count" if msg.status == Message.Status.SENT else "failed_count"
        Campaign.objects.filter(pk=msg.campaign_id).update(**{field: F(field) + 1})
        campaign = Campaign.objects.get(pk=msg.campaign_id)
        if campaign.sent_count + campaign.failed_count >= campaign.total_recipients:
            campaign.status = Campaign.Status.DONE
            campaign.save(update_fields=["status", "updated_at"])
    if not result.ok and self.request.retries < self.max_retries:
        raise RuntimeError(f"Send failed, retrying: {result.error}")


@shared_task
def dispatch_campaign(campaign_id: int):
    """Resolve the audience into Message rows and queue individual sends."""
    from apps.accounts.models import User
    from apps.provisioning.models import Session

    from .models import Campaign, Message

    campaign = Campaign.objects.get(pk=campaign_id)
    customers = User.objects.filter(is_staff=False, is_active=True).exclude(phone="")
    if campaign.audience == Campaign.Audience.ACTIVE:
        customers = customers.filter(sessions__status=Session.Status.ACTIVE)
    elif campaign.audience == Campaign.Audience.EXPIRED:
        customers = customers.filter(sessions__isnull=False).exclude(
            sessions__status=Session.Status.ACTIVE
        )
    phones = list(customers.values_list("phone", flat=True).distinct())

    messages = Message.objects.bulk_create(
        Message(
            operator=campaign.operator,
            campaign=campaign,
            to_phone=phone,
            channel=campaign.channel,
            body=campaign.body,
        )
        for phone in phones
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
