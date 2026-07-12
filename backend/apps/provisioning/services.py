import logging
import secrets

from django.utils import timezone

from apps.core.services import audit

from .adapters import get_adapter
from .models import Router, Session

logger = logging.getLogger(__name__)


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


class ReprovisionError(Exception):
    """Something the ISP can fix (the payment isn't complete, no router). Safe to show."""


def reprovision_transaction(tx, *, actor=None, compensate: bool = True):
    """The ISP (or support) reconnecting a paid customer who never got online.

    This is the human-authorised recovery for "payment came through — including via
    reconciliation — but the customer never connected". Unlike the automatic beat
    retry, which is conservative and only touches sessions still inside their window,
    this is a person saying "yes, reconnect them", so it COMPENSATES: the customer paid
    for the full plan and received nothing, so their time starts fresh from now.

    Returns the session, left in PENDING with a re-attempt queued. The dashboard then
    shows it going connecting -> active exactly like a first-time payment.
    """
    from apps.payments.models import Transaction

    if tx.status not in Transaction.SUCCESS_STATUSES:
        raise ReprovisionError("This payment hasn't completed, so there's nothing to reconnect.")

    try:
        session = create_session_for_transaction(tx)
    except Router.DoesNotExist as exc:
        raise ReprovisionError(
            "No active router to connect them to. Add or bring a router online first."
        ) from exc

    now = timezone.now()
    if compensate or session.expires_at <= now:
        # Fresh full window — they got zero service for what they paid.
        session.starts_at = now
        session.expires_at = now + tx.plan.duration
    session.status = Session.Status.PENDING
    session.provision_error = ""
    session.save(
        update_fields=["starts_at", "expires_at", "status", "provision_error", "updated_at"]
    )

    # Clear any transaction-level failure note so the portal/dashboard flip to
    # "connecting" immediately.
    if tx.provision_error:
        tx.provision_error = ""
        tx.save(update_fields=["provision_error", "updated_at"])

    audit(
        "session_reconnected",
        operator=tx.operator,
        actor=actor,
        target=session,
        transaction=str(tx.public_id),
        compensated=compensate,
        new_expiry=session.expires_at.isoformat(),
    )

    from .tasks import activate_session

    activate_session.delay(session.id)
    return session


def activate(session: Session) -> None:
    """Push credentials to the router. Raises on failure so Celery retries."""
    if session.status == Session.Status.ACTIVE:
        return  # already on — and the early return also means we notify exactly once
    result = get_adapter(session.router).activate_user(session)
    session.status = Session.Status.ACTIVE
    session.provision_error = ""
    # A fresh/renewed window hasn't been warned yet — reset both nudges and the usage
    # counter so a renewal starts clean.
    session.expiry_warned_at = None
    session.data_warned_at = None
    session.data_used_mb = 0
    session.save(
        update_fields=[
            "status", "provision_error", "expiry_warned_at",
            "data_warned_at", "data_used_mb", "updated_at",
        ]
    )
    audit(
        "session_activated",
        operator=session.operator,
        target=session,
        router=session.router.name,
        message=result.message,
    )
    # "You're online" — the receipt. Best-effort: a failed SMS must never fail the
    # activation the customer already paid for.
    try:
        from apps.notifications.services import notify_online

        notify_online(session)
    except Exception:
        logger.exception("Could not queue the online-confirmation SMS for session %s", session.pk)


def suspend(session: Session, new_status: str | None = None) -> None:
    get_adapter(session.router).suspend_user(session)
    if new_status:
        session.status = new_status
        session.save(update_fields=["status", "updated_at"])
    audit("session_suspended", operator=session.operator, target=session, status=session.status)
