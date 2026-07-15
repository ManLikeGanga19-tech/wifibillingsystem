import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def provision_client_task(self, client_id: int):
    from .models import Client
    from .services import provision_client

    provision_client(Client.objects.select_related("plan", "router", "operator").get(pk=client_id))


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def suspend_client_task(self, client_id: int):
    from .models import Client
    from .services import suspend_client

    suspend_client(Client.objects.select_related("router", "operator").get(pk=client_id))


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def restore_client_task(self, client_id: int):
    from .models import Client
    from .services import restore_client

    restore_client(Client.objects.select_related("router", "operator", "plan").get(pk=client_id))


@shared_task
def issue_due_invoices():
    """Daily: issue this month's invoice for every active client whose billing day
    is today. Anniversary billing.

    Skips operators who have turned auto-generation OFF — they issue invoices by hand.
    The set of such operators is tiny (it is off by exception), so we resolve it once and
    filter, rather than checking per client."""
    from .models import Client, PppoeSettings
    from .services import issue_invoice

    today = timezone.localdate()
    manual = set(
        PppoeSettings.objects.filter(auto_generate_invoices=False).values_list(
            "operator_id", flat=True
        )
    )
    issued = 0
    clients = (
        Client.objects.filter(status__in=Client.ACTIVE_STATUSES, billing_day=today.day)
        .exclude(operator_id__in=manual)
        .select_related("plan", "operator")
    )
    for client in clients.iterator():
        if issue_invoice(client, today):
            issued += 1
    if issued:
        logger.info("Issued %d PPPoE invoices", issued)
    return issued


@shared_task
def prune_dormant_pppoe_clients():
    """Daily: delete dormant DISABLED accounts for ISPs who opted in (see lifecycle)."""
    from .lifecycle import prune_dormant_clients

    return prune_dormant_clients()


@shared_task
def remind_pppoe_expiry():
    """Hourly: SMS subscribers ahead of renewal, per each ISP's chosen lead times."""
    from .lifecycle import remind_expiring_clients

    return remind_expiring_clients()


@shared_task
def poll_pppoe_usage():
    """Every 5 min: meter live PPPoE usage off every router and fire FUP alerts."""
    from .metering import poll_all

    return poll_all()


@shared_task
def suspend_overdue_clients():
    """Daily: suspend active clients with an overdue balance past due date."""
    from .models import Client, Invoice
    from .services import suspend_client

    today = timezone.localdate()
    suspended = 0
    overdue_client_ids = (
        Invoice.objects.filter(status__in=Invoice.OPEN_STATUSES, due_date__lt=today)
        .values_list("client_id", flat=True)
        .distinct()
    )
    clients = Client.objects.filter(
        id__in=list(overdue_client_ids), status=Client.Status.ACTIVE, balance__lt=0
    ).select_related("router", "operator")
    for client in clients.iterator():
        # mark those invoices overdue for reporting
        Invoice.objects.filter(
            client=client, status=Invoice.Status.UNPAID, due_date__lt=today
        ).update(status=Invoice.Status.OVERDUE)
        suspend_client(client, reason="overdue")
        suspended += 1
    if suspended:
        logger.info("Suspended %d overdue PPPoE clients", suspended)
    return suspended
