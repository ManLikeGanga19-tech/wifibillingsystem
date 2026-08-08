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

from .models import (
    Client,
    ClientLifecycleEvent,
    Invoice,
    ServicePlan,
    generate_account_number,
    month_period,
)

logger = logging.getLogger(__name__)


def _pppoe_password() -> str:
    return secrets.token_urlsafe(9)


def _record_transition(
    client: Client,
    *,
    event: str,
    to_status: str,
    reason: str = "",
    actor=None,
    extra_fields: tuple[str, ...] = (),
) -> None:
    """The single chokepoint for a status change: move the client, stamp when it happened,
    and write an immutable ClientLifecycleEvent so churn analytics has a dated trail.

    Every real transition (activate / suspend / restore / cancel) goes through here, so the
    log can never silently miss one. Callers set any side fields (e.g. installed_at) on the
    instance first and name them in extra_fields; they are persisted in the same save."""
    from_status = client.status
    client.status = to_status
    client.status_changed_at = timezone.now()
    client.save(update_fields=["status", "status_changed_at", "updated_at", *extra_fields])
    ClientLifecycleEvent.objects.create(
        operator=client.operator,
        client=client,
        account_number=client.account_number,
        full_name=client.full_name,
        event=event,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
    )


def _emit(operator, event: str, data: dict) -> None:
    """Fan a subscriber/payment event out to the ISP's webhooks (Settings > Developer). Isolated
    from the caller — a webhook must never break a suspension or a recorded payment."""
    try:
        from apps.developer.dispatch import emit_event

        emit_event(operator, event, data)
    except Exception:
        logger.exception("emit_event failed for %s", event)


def _client_payload(client) -> dict:
    return {
        "id": client.pk,
        "account_number": client.account_number,
        "full_name": client.full_name,
        "phone": client.phone,
        "plan": client.plan.name if client.plan_id else None,
        "status": client.status,
    }


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
    _emit(operator, "subscriber.created", _client_payload(client))
    return client


def provision_client(client: Client) -> None:
    """Push the plan profile + client secret to the router. Called after install."""
    adapter = get_adapter(client.router)
    # Router-wide TCP-MSS clamp: a PPPoE link's MTU (~1480) is below Ethernet's 1500, and the
    # many sites that break Path-MTU Discovery then hang or half-load for the customer. One
    # idempotent rule per router fixes it for every client on it — for EVERY tenant's routers,
    # not just ours. Best-effort: never fail a provisioning the ISP just asked for.
    try:
        adapter.ensure_pppoe_mss_clamp()
    except Exception:
        logger.exception("Could not ensure the MSS clamp on router %s", client.router_id)
    adapter.ensure_pppoe_profile(client.plan)
    adapter.create_pppoe_user(client)
    # PENDING_INSTALL -> ACTIVE is a first activation; CANCELLED -> ACTIVE is a win-back of a
    # churned customer (re-provisioning revives them). Both are counted, with distinct events.
    first_activation = client.status == Client.Status.PENDING_INSTALL
    reviving = client.status in (Client.Status.PENDING_INSTALL, Client.Status.CANCELLED)
    if reviving:
        if not client.installed_at:
            client.installed_at = timezone.localdate()
        _record_transition(
            client,
            event=(
                ClientLifecycleEvent.Event.ACTIVATED
                if first_activation
                else ClientLifecycleEvent.Event.REACTIVATED
            ),
            to_status=Client.Status.ACTIVE,
            extra_fields=("installed_at",),
        )
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
    _record_transition(
        client,
        event=ClientLifecycleEvent.Event.SUSPENDED,
        to_status=Client.Status.SUSPENDED,
        reason=reason,
    )
    audit("pppoe_client_suspended", operator=client.operator, target=client, reason=reason)
    _emit(client.operator, "subscriber.paused", {**_client_payload(client), "reason": reason})
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
    _record_transition(
        client,
        event=ClientLifecycleEvent.Event.RESTORED,
        to_status=Client.Status.ACTIVE,
    )
    audit("pppoe_client_restored", operator=client.operator, target=client)
    _emit(client.operator, "subscriber.resumed", _client_payload(client))


def cancel_client(client: Client, *, reason: str = "churned", actor=None) -> None:
    """Mark an overdue account as churned: pull its secret off the router and stop billing
    it. Only a SUSPENDED account can be cancelled — a live customer is never churned, and a
    cancel is the terminal admission that a suspended one is not coming back. Removing the
    secret is best-effort: a cancelled client must leave the books even if their router is
    unreachable at that moment."""
    if client.status != Client.Status.SUSPENDED:
        return
    try:
        get_adapter(client.router).remove_pppoe_user(client)
    except Exception:
        logger.exception("Could not remove the secret for churned client %s", client.pk)
    _record_transition(
        client,
        event=ClientLifecycleEvent.Event.CANCELLED,
        to_status=Client.Status.CANCELLED,
        reason=reason,
        actor=actor,
    )
    audit("pppoe_client_cancelled", operator=client.operator, actor=actor,
          target=client, reason=reason)
    _emit(client.operator, "subscriber.cancelled", _client_payload(client))


#: Fields an edit may change that the ROUTER also needs to know about. Everything else
#: (name, phone, email, address, billing day, notes…) is bookkeeping the router never sees.
ROUTER_VISIBLE_FIELDS = ("plan_id", "router_id", "static_ip")


def update_client(client: Client, *, changes: dict, actor=None) -> Client:
    """Apply an edit AND make the router agree with it.

    The trap this closes: saving only the database leaves the MikroTik still enforcing the
    OLD plan (or still holding the secret on the OLD router), so the console and the network
    disagree and nobody can tell which is true. So:

      * plan changed      -> ensure the new profile exists, re-push the secret onto it, and
                             kick the live session so the new SPEED takes effect now (a
                             PPPoE session keeps its old queue until it redials).
      * router changed    -> MIGRATE: create the secret on the new router first, and only
                             then remove it from the old one, so a failure can never leave
                             the customer with no secret anywhere.
      * suspended client  -> stays on the suspended profile; an edit must never silently
                             reconnect someone who has not paid.

    Router work happens only when a router-visible field actually changed, and it happens
    AFTER the DB commit, so a provisioning error can't leave the record half-written. On
    such an error the DB change stands and the caller is told, rather than pretending.
    """
    old_plan_id, old_router = client.plan_id, client.router
    for field, value in changes.items():
        setattr(client, field, value)

    with db_transaction.atomic():
        client.save()

    plan_changed = "plan_id" in changes and changes["plan_id"] != old_plan_id
    router_changed = "router_id" in changes and changes["router_id"] != old_router.pk
    if not (plan_changed or router_changed or "static_ip" in changes):
        audit("pppoe_client_updated", operator=client.operator, actor=actor, target=client,
              fields=sorted(changes))
        return client

    client.refresh_from_db()
    if client.status not in Client.ACTIVE_STATUSES:
        # Not on any router yet (pending install) — the secret gets written at provision
        # time with whatever the record says by then. Nothing to reconcile.
        audit("pppoe_client_updated", operator=client.operator, actor=actor, target=client,
              fields=sorted(changes))
        return client

    new_adapter = get_adapter(client.router)
    new_adapter.ensure_pppoe_profile(client.plan)
    new_adapter.create_pppoe_user(client)  # idempotent upsert on the (possibly new) router
    if client.status == Client.Status.SUSPENDED:
        # create_pppoe_user writes the ACTIVE plan profile; a suspended client must stay
        # walled off, so put them back on the suspended profile.
        new_adapter.set_pppoe_enabled(client, False)

    if router_changed:
        # Only now that the new router holds the secret is it safe to drop the old one —
        # and a failure there must not fail the edit: the client is already served.
        try:
            get_adapter(old_router).remove_pppoe_user(client)
        except Exception:
            logger.exception(
                "Client %s moved to router %s but the secret could not be removed from %s",
                client.pk, client.router_id, old_router.pk,
            )
    elif plan_changed and client.status == Client.Status.ACTIVE:
        # A live PPPoE session keeps its old queue until it redials, so the customer would
        # not see their new speed. Bounce it: they reconnect within seconds, at the new rate.
        # Best-effort — the secret is already correct, so a failed kick only delays the new
        # speed until their next reconnect; it must not fail the edit.
        try:
            new_adapter.kick_pppoe_session(client)
        except Exception:
            logger.exception("Could not bounce %s onto its new plan", client.pppoe_username)

    audit("pppoe_client_updated", operator=client.operator, actor=actor, target=client,
          fields=sorted(changes), plan_changed=plan_changed, router_changed=router_changed)
    _emit(client.operator, "subscriber.updated", _client_payload(client))
    return client


def reset_pppoe_password(client: Client, *, password: str = "", actor=None) -> str:
    """Set a new PPPoE password — the one supplied, or a freshly generated strong one — and
    push it to the router live. Returns the new password so the ISP can hand it to the
    installer. Only touches the router if the secret should already exist there; a client
    that isn't installed yet just gets the new password stored, to be written at provision.
    """
    new_password = password or _pppoe_password()
    client.pppoe_password = new_password
    client.save(update_fields=["pppoe_password", "updated_at"])
    if client.status in Client.ACTIVE_STATUSES:  # ACTIVE or SUSPENDED — secret is on the box
        adapter = get_adapter(client.router)
        adapter.create_pppoe_user(client)  # idempotent: patches the secret's password
        # create_pppoe_user rewrites the ACTIVE plan profile; a suspended client must stay
        # on the suspended profile, so re-apply it.
        if client.status == Client.Status.SUSPENDED:
            adapter.set_pppoe_enabled(client, False)
    audit("pppoe_password_reset", operator=client.operator, actor=actor, target=client)
    return new_password


def delete_client(client: Client, *, actor=None) -> None:
    """Remove the client's secret (and kick any live session) from the router, THEN delete
    the record — so no orphaned /ppp/secret is left behind. If the router can't be reached
    the removal raises and the record is kept, so a secret is never orphaned silently."""
    get_adapter(client.router).remove_pppoe_user(client)
    audit(
        "pppoe_client_deleted", operator=client.operator, actor=actor, target=client,
        account_number=client.account_number, pppoe_username=client.pppoe_username,
    )
    _emit(client.operator, "subscriber.deleted", _client_payload(client))
    client.delete()


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
    _emit(client.operator, "payment.received",
          {**_client_payload(client), "amount": str(amount), "source": source})
