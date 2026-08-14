from django.utils import timezone

from .models import AuditLog, TenantLifecycleEvent


def audit(action: str, *, operator=None, actor=None, target=None, ip=None, **metadata):
    AuditLog.objects.create(
        operator=operator,
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(getattr(target, "pk", "")) if target is not None else "",
        metadata=metadata,
        ip_address=ip,
    )


def record_tenant_event(operator, event, *, from_status="", actor=None, reason="", when=None):
    """Append one row to the tenant lifecycle log — the source of truth for tenant churn.

    Call this at the moments a tenant's live-ness flips (activation / suspension), NOT on
    every save. `from_status` is the operator's status BEFORE the flip (read it before you
    mutate). The demo tenant earns no real revenue and never counts as churn, so it is
    skipped here rather than filtered in every downstream query."""
    if getattr(operator, "is_demo", False):
        return None
    return TenantLifecycleEvent.objects.create(
        operator=operator,
        slug=operator.slug,
        name=operator.name,
        event=event,
        from_status=from_status or "",
        to_status=operator.status,
        reason=(reason or "")[:200],
        actor=actor if getattr(actor, "pk", None) else None,
        occurred_at=when or timezone.now(),
    )
