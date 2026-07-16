"""PPPoE business logic: provisioning, invoicing (anniversary), suspend/restore,
and C2B payment matching. Money always flows via the wallet ledger."""

import logging
import secrets
from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.core.services import audit
from apps.provisioning.adapters import get_adapter

from .models import Client, Invoice, ServicePlan, generate_account_number, month_period

logger = logging.getLogger(__name__)


def _pppoe_password() -> str:
    return secrets.token_urlsafe(9)


#: Account numbers are a random tail checked against the database. That check and the
#: INSERT are not atomic, so two clients signing up at the same instant can both pass it
#: and then collide on the unique column. Rare — but "rare" here means a real customer
#: getting a 500 in front of an installer, so we simply try again with a fresh number.
ACCOUNT_NUMBER_ATTEMPTS = 5


def create_client(*, operator, plan: ServicePlan, router, created_by=None, **fields) -> Client:
    """Create a broadband client with a globally-unique account number and PPPoE
    credentials. Provisioning to the router happens separately (provision_client)."""
    username = fields.pop("pppoe_username", "") or f"{operator.slug}-{secrets.token_hex(3)}"
    password = fields.pop("pppoe_password", "") or _pppoe_password()

    for attempt in range(ACCOUNT_NUMBER_ATTEMPTS):
        try:
            with db_transaction.atomic():
                client = Client.objects.create(
                    operator=operator,
                    plan=plan,
                    router=router,
                    account_number=generate_account_number(operator),
                    pppoe_username=username,
                    pppoe_password=password,
                    created_by=created_by,
                    **fields,
                )
            break
        except IntegrityError:
            # Lost the race for that number. Any OTHER integrity error (a duplicate PPPoE
            # username, say) is a real fault and must not be retried into oblivion.
            if not Client.objects.filter(pppoe_username=username).exists():
                if attempt == ACCOUNT_NUMBER_ATTEMPTS - 1:
                    raise
                continue
            raise
    audit("pppoe_client_created", operator=operator, actor=created_by, target=client)
    return client


def provision_client(client: Client) -> None:
    """Push the plan profile + client secret to the router. Called after install."""
    adapter = get_adapter(client.router)
    adapter.ensure_pppoe_profile(client.plan)
    adapter.create_pppoe_user(client)
    first_activation = client.status == Client.Status.PENDING_INSTALL
    if first_activation:
        client.status = Client.Status.ACTIVE
        if not client.installed_at:
            client.installed_at = timezone.localdate()
        client.save(update_fields=["status", "installed_at", "updated_at"])
    audit("pppoe_client_provisioned", operator=client.operator, target=client)
    # Welcome + login details on FIRST activation only. Best-effort — a failed SMS must
    # never fail a provisioning the ISP just did.
    if first_activation:
        try:
            from apps.notifications.services import notify_pppoe_welcome

            notify_pppoe_welcome(client)
        except Exception:
            logger.exception("Could not queue the PPPoE welcome SMS for client %s", client.pk)


def suspend_client(client: Client, *, reason: str = "overdue") -> None:
    if client.status not in Client.ACTIVE_STATUSES:
        return
    get_adapter(client.router).set_pppoe_enabled(client, False)
    client.status = Client.Status.SUSPENDED
    client.save(update_fields=["status", "updated_at"])
    audit("pppoe_client_suspended", operator=client.operator, target=client, reason=reason)
    # "Your package has expired — pay to reconnect." Best-effort.
    try:
        from apps.notifications.services import notify_pppoe_expired

        notify_pppoe_expired(client)
    except Exception:
        logger.exception("Could not queue the PPPoE expired SMS for client %s", client.pk)


def restore_client(client: Client) -> None:
    if client.status != Client.Status.SUSPENDED:
        return
    get_adapter(client.router).set_pppoe_enabled(client, True)
    client.status = Client.Status.ACTIVE
    client.save(update_fields=["status", "updated_at"])
    audit("pppoe_client_restored", operator=client.operator, target=client)


# ---- invoicing (anniversary) ----------------------------------------------


def _invoice_number(operator, period_start) -> str:
    from .models import PppoeSettings

    row = PppoeSettings.objects.filter(operator=operator).first()
    prefix = (row.invoice_prefix if row and row.invoice_prefix else "INV").strip() or "INV"
    return f"{prefix}-{operator.id}-{period_start:%Y%m}-{secrets.randbelow(10000):04d}"


def issue_invoice(client: Client, period_start, *, grace_days: int = 3) -> Invoice | None:
    """Create this month's invoice for a client (idempotent per period). Reduces
    the client's running balance; due date = period start + grace."""
    start, end = month_period(period_start)
    existing = Invoice.objects.filter(client=client, period_start=start).first()
    if existing:
        return existing
    from datetime import timedelta

    with db_transaction.atomic():
        invoice = Invoice.objects.create(
            operator=client.operator,
            client=client,
            number=_invoice_number(client.operator, start),
            period_start=start,
            period_end=end,
            amount=client.plan.price,
            due_date=start + timedelta(days=grace_days),
        )
        client.balance = client.balance - client.plan.price
        client.next_due_date = invoice.due_date
        client.save(update_fields=["balance", "next_due_date", "updated_at"])
    audit(
        "pppoe_invoice_issued",
        operator=client.operator,
        target=invoice,
        amount=str(invoice.amount),
    )
    return invoice


def apply_payment_to_invoices(client: Client) -> None:
    """After a payment credits the client's balance, settle open invoices oldest
    first while the balance covers them, and restore service if it was suspended."""
    open_invoices = client.invoices.filter(
        status__in=Invoice.OPEN_STATUSES
    ).order_by("period_start")
    for invoice in open_invoices:
        if client.balance >= invoice.amount or client.balance >= 0:
            invoice.status = Invoice.Status.PAID
            invoice.paid_at = timezone.now()
            invoice.save(update_fields=["status", "paid_at"])
    # Fully settled (no debt) -> restore
    if client.balance >= 0 and client.status == Client.Status.SUSPENDED:
        restore_client(client)


def record_client_payment(client: Client, amount: Decimal, *, source: str, memo: str = "") -> None:
    """Credit a client's account balance and settle invoices. Also credits the
    ISP's wallet (money is held centrally by the platform)."""
    from apps.billing.services import credit_pppoe_payment

    with db_transaction.atomic():
        client = Client.objects.select_for_update().get(pk=client.pk)
        client.balance = client.balance + amount
        client.save(update_fields=["balance", "updated_at"])
        credit_pppoe_payment(client.operator, amount, memo=memo or f"PPPoE {client.account_number}")
        apply_payment_to_invoices(client)
    audit("pppoe_payment_recorded", operator=client.operator, target=client,
          amount=str(amount), source=source)
