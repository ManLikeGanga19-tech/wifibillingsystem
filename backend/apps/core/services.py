from .models import AuditLog


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
