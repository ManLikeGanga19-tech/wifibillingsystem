from .models import AuditLog, Operator


def get_default_operator() -> Operator:
    """Phase 1 runs single-tenant: everything belongs to the first active operator."""
    op = Operator.objects.filter(is_active=True).order_by("id").first()
    if op is None:
        raise Operator.DoesNotExist(
            "No active Operator exists. Run `manage.py seed_dev` or create one in /admin/."
        )
    return op


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
