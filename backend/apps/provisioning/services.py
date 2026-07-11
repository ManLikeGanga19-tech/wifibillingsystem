import secrets

from django.utils import timezone

from apps.core.services import audit

from .adapters import get_adapter
from .models import Router, Session


def _hotspot_password() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def refresh_device_identity(router) -> "object":
    """Fetch the router's device info and persist its stable identity fields.
    Returns the DeviceInfo (with live metrics) for the caller to surface.
    Best-effort: never raises — identity is a nice-to-have, not critical path."""
    from .adapters import ProvisioningError, get_adapter

    try:
        info = get_adapter(router).get_device_info()
    except ProvisioningError:
        return None
    changed = []
    for field in ("routeros_version", "board_name", "serial_number", "architecture"):
        value = getattr(info, field)
        if value and getattr(router, field) != value:
            setattr(router, field, value)
            changed.append(field)
    router.identity_updated_at = timezone.now()
    changed.append("identity_updated_at")
    router.save(update_fields=[*changed, "updated_at"])
    return info


def pick_router(operator, preferred=None) -> Router:
    # SECURITY: a preferred router is only honoured if it belongs to this operator.
    # Otherwise a tenant could provision a session onto another ISP's physical
    # router by passing its id (found in the voucher-redeem audit).
    if preferred and preferred.is_active and preferred.operator_id == operator.id:
        return preferred
    router = Router.objects.filter(operator=operator, is_active=True).order_by("id").first()
    if router is None:
        raise Router.DoesNotExist(
            "No active router configured. Add one in /admin/ before provisioning."
        )
    return router


def create_session_for_transaction(tx) -> Session:
    """Idempotent: one session per transaction (OneToOne)."""
    existing = Session.objects.filter(transaction=tx).first()
    if existing:
        return existing
    now = timezone.now()
    return Session.objects.create(
        operator=tx.operator,
        subscriber=tx.subscriber,
        plan=tx.plan,
        router=pick_router(tx.operator, tx.router),
        transaction=tx,
        hotspot_username=tx.phone,
        hotspot_password=_hotspot_password(),
        starts_at=now,
        expires_at=now + tx.plan.duration,
        mac_address=tx.mac_address,
    )


def create_session_for_voucher(voucher, mac: str = "", router=None) -> Session:
    """Voucher holders log into the hotspot with the voucher code itself."""
    existing = Session.objects.filter(voucher=voucher).first()
    if existing:
        return existing
    now = timezone.now()
    return Session.objects.create(
        operator=voucher.operator,
        subscriber=voucher.redeemed_by,
        plan=voucher.plan,
        router=pick_router(voucher.operator, router),
        voucher=voucher,
        hotspot_username=voucher.code,
        hotspot_password=voucher.code,
        starts_at=now,
        expires_at=now + voucher.plan.duration,
        mac_address=mac,
    )


def activate(session: Session) -> None:
    """Push credentials to the router. Raises on failure so Celery retries."""
    if session.status == Session.Status.ACTIVE:
        return
    result = get_adapter(session.router).activate_user(session)
    session.status = Session.Status.ACTIVE
    session.provision_error = ""
    session.save(update_fields=["status", "provision_error", "updated_at"])
    audit(
        "session_activated",
        operator=session.operator,
        target=session,
        router=session.router.name,
        message=result.message,
    )


def suspend(session: Session, new_status: str | None = None) -> None:
    get_adapter(session.router).suspend_user(session)
    if new_status:
        session.status = new_status
        session.save(update_fields=["status", "updated_at"])
    audit("session_suspended", operator=session.operator, target=session, status=session.status)
