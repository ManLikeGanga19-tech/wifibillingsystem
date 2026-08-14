"""Tenant offboarding — removing an ISP from the platform, safely.

The lifecycle is a small state machine with a reversible middle:

    ACTIVE ──initiate──▶ SCHEDULED ──complete──▶ COMPLETED (terminal)
                            │
                            └────abort────▶ reinstated (ACTIVE again)

Initiating only FREEZES the tenant (suspends the console, snapshots the money) and starts a
grace window — nothing on the network is touched, so an accidental or disputed offboarding
costs nothing to undo. Completing is the irreversible act: it pulls every subscriber's
service off the router and drops the tenant to a CANCELLED terminal state. All of it is
audited and works for ANY tenant (see [[tenant-based-everything]])."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Operator, TenantLifecycleEvent, TenantOffboarding
from .services import audit, record_tenant_event

DEFAULT_GRACE_DAYS = 14


class OffboardingError(Exception):
    """A refused offboarding transition (wrong state, missing reason, demo tenant…)."""


def financial_snapshot(operator: Operator) -> dict:
    """What the final settlement hinges on, as of now. Positive `withdrawable` = WE owe THEM
    (pay it out); positive `owed` = THEY owe US (collect before closing)."""
    from apps.billing.services import amount_owed, withdrawable_balance
    from apps.pppoe.models import Client

    return {
        "withdrawable": withdrawable_balance(operator),
        "owed": amount_owed(operator),
        "active_subscribers": Client.objects.filter(
            operator=operator, status__in=Client.ACTIVE_STATUSES
        ).count(),
    }


def current_offboarding(operator: Operator) -> TenantOffboarding | None:
    """The live (scheduled) offboarding for this tenant, if any."""
    return operator.offboardings.filter(
        state=TenantOffboarding.State.SCHEDULED
    ).first()


@transaction.atomic
def initiate_offboarding(
    operator: Operator, *, reason: str, actor=None, grace_days: int = DEFAULT_GRACE_DAYS
) -> TenantOffboarding:
    """Begin offboarding: freeze the console and open a grace window. Nothing on the network
    is torn down yet — this step is fully reversible via abort_offboarding."""
    reason = (reason or "").strip()
    if not reason:
        raise OffboardingError("An offboarding reason is required.")
    if operator.is_demo:
        raise OffboardingError("The demo tenant cannot be offboarded.")
    if operator.is_platform_owned:
        raise OffboardingError("The platform's own tenant cannot be offboarded.")
    if current_offboarding(operator) is not None:
        raise OffboardingError("This tenant is already being offboarded.")

    snap = financial_snapshot(operator)
    was = operator.status

    # Freeze: the same door as a manual suspension (console locked), plus the terminal intent
    # recorded separately. Keep is_active True through grace so records stay reachable and undo
    # is trivial.
    operator.status = Operator.Status.SUSPENDED
    operator.suspension_reason = f"Offboarding: {reason}"[:200]
    operator.save(update_fields=["status", "suspension_reason", "updated_at"])
    if was != Operator.Status.SUSPENDED:
        record_tenant_event(
            operator, TenantLifecycleEvent.Event.SUSPENDED,
            from_status=was, actor=actor, reason=f"offboarding: {reason}",
        )

    ob = TenantOffboarding.objects.create(
        operator=operator,
        reason=reason,
        initiated_by=actor if getattr(actor, "pk", None) else None,
        grace_until=timezone.now() + timedelta(days=max(0, grace_days)),
        snapshot_withdrawable=snap["withdrawable"],
        snapshot_owed=snap["owed"],
    )
    audit("tenant_offboarding_initiated", operator=operator, actor=actor, target=operator,
          reason=reason, grace_until=ob.grace_until.isoformat(),
          withdrawable=str(snap["withdrawable"]), owed=str(snap["owed"]))
    return ob


@transaction.atomic
def abort_offboarding(operator: Operator, *, actor=None) -> TenantOffboarding:
    """Reinstate a tenant still in its grace window. Reverses the freeze through the SAME
    activation service as a normal restore, so the tenant lands in a consistent live state."""
    from .settlement import activate_operator

    ob = current_offboarding(operator)
    if ob is None:
        raise OffboardingError("This tenant has no offboarding to abort.")

    operator.suspension_reason = ""
    operator.save(update_fields=["suspension_reason", "updated_at"])
    activate_operator(operator, actor=actor, reason="offboarding aborted")

    ob.state = TenantOffboarding.State.ABORTED
    ob.resolved_by = actor if getattr(actor, "pk", None) else None
    ob.resolved_at = timezone.now()
    ob.save(update_fields=["state", "resolved_by", "resolved_at"])
    audit("tenant_offboarding_aborted", operator=operator, actor=actor, target=operator)
    return ob


@transaction.atomic
def complete_offboarding(
    operator: Operator, *, actor=None, force: bool = False
) -> TenantOffboarding:
    """The terminal act: tear every subscriber's service off the router and drop the tenant to
    a CANCELLED terminal state. Allowed once the grace window has elapsed, or immediately when
    an owner forces it. Kept records; revoked access."""
    from apps.pppoe.models import Client
    from apps.pppoe.services import force_cancel_client

    ob = current_offboarding(operator)
    if ob is None:
        raise OffboardingError("This tenant has no scheduled offboarding to complete.")
    if not force and ob.grace_until > timezone.now():
        raise OffboardingError(
            "Still in the grace window — wait it out or complete with force."
        )

    # Pull every live/suspended subscriber off the network. Best-effort per client (a single
    # unreachable router must not strand the whole offboarding); the count is what actually
    # tore down.
    torn = 0
    for client in Client.objects.filter(operator=operator).exclude(
        status=Client.Status.CANCELLED
    ):
        force_cancel_client(client, reason="operator offboarded", actor=actor)
        torn += 1

    # Terminal: console stays suspended AND the hard kill-switch goes off, so nothing can
    # transact again without a deliberate platform action.
    operator.status = Operator.Status.SUSPENDED
    operator.is_active = False
    operator.save(update_fields=["status", "is_active", "updated_at"])
    record_tenant_event(
        operator, TenantLifecycleEvent.Event.CANCELLED,
        from_status=Operator.Status.SUSPENDED, actor=actor, reason=ob.reason,
    )

    snap = financial_snapshot(operator)  # refresh at the close
    ob.state = TenantOffboarding.State.COMPLETED
    ob.resolved_by = actor if getattr(actor, "pk", None) else None
    ob.resolved_at = timezone.now()
    ob.snapshot_withdrawable = snap["withdrawable"]
    ob.snapshot_owed = snap["owed"]
    ob.subscribers_torn_down = torn
    ob.save(update_fields=[
        "state", "resolved_by", "resolved_at",
        "snapshot_withdrawable", "snapshot_owed", "subscribers_torn_down",
    ])
    audit("tenant_offboarding_completed", operator=operator, actor=actor, target=operator,
          subscribers_torn_down=torn, forced=force,
          withdrawable=str(snap["withdrawable"]), owed=str(snap["owed"]))
    return ob


def export_tenant_data(operator: Operator) -> dict:
    """A portable snapshot of the tenant's own records — handed over on offboarding so an ISP
    leaves WITH its data. Scoped strictly to this operator; no cross-tenant leakage."""
    from apps.billing.models import LedgerEntry
    from apps.payments.models import Transaction
    from apps.pppoe.models import Client, ServicePlan

    def _clients():
        for c in Client.objects.filter(operator=operator).order_by("id"):
            yield {
                "account_number": c.account_number,
                "full_name": c.full_name,
                "phone": c.phone,
                "connection_type": c.connection_type,
                "static_ip": c.static_ip,
                "plan": c.plan.name if c.plan_id else None,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
            }

    def _plans():
        for p in ServicePlan.objects.filter(operator=operator).order_by("id"):
            yield {
                "name": p.name, "price": str(p.price),
                "download_kbps": p.download_kbps, "upload_kbps": p.upload_kbps,
            }

    fin = financial_snapshot(operator)
    return {
        "exported_at": timezone.now().isoformat(),
        "operator": {
            "name": operator.name,
            "slug": operator.slug,
            "contact_email": operator.contact_email,
            "contact_phone": operator.contact_phone,
            "status": operator.status,
        },
        "financials": {
            "withdrawable_balance": str(fin["withdrawable"]),
            "amount_owed": str(fin["owed"]),
        },
        "service_plans": list(_plans()),
        "subscribers": list(_clients()),
        "recent_transactions": [
            {
                "amount": str(t.amount), "status": t.status, "phone": t.phone,
                "created_at": t.created_at.isoformat(),
            }
            for t in Transaction.objects.filter(operator=operator).order_by("-created_at")[:500]
        ],
        "ledger_total": str(
            LedgerEntry.objects.filter(operator=operator).aggregate(s=Sum("amount"))["s"]
            or Decimal("0")
        ),
    }
