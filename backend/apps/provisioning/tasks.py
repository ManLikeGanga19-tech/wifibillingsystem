import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

RETRY_KWARGS = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 5,
}


@shared_task(bind=True, **RETRY_KWARGS)
def provision_transaction(self, transaction_id: int):
    """Paid transaction -> session on the router. Retries with backoff; a paid
    customer must never be lost because a router blinked."""
    from apps.payments.models import Transaction

    from . import services

    tx = Transaction.objects.select_related("plan", "operator", "subscriber", "router").get(
        pk=transaction_id
    )
    if tx.status not in Transaction.SUCCESS_STATUSES:
        logger.warning("provision_transaction called for non-paid tx %s (%s)", tx.pk, tx.status)
        return
    session = services.create_session_for_transaction(tx)
    try:
        services.activate(session)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            session.status = session.Status.FAILED
            session.provision_error = str(exc)[:255]
            session.save(update_fields=["status", "provision_error", "updated_at"])
            logger.error("Session %s permanently failed to provision: %s", session.pk, exc)
        raise


@shared_task(bind=True, **RETRY_KWARGS)
def activate_session(self, session_id: int):
    """Provision an already-created session (voucher redemptions)."""
    from .models import Session
    from .services import activate

    activate(Session.objects.select_related("plan", "router", "operator").get(pk=session_id))


@shared_task(bind=True, **RETRY_KWARGS)
def suspend_session(self, session_id: int, new_status: str | None = None):
    from .models import Session
    from .services import suspend

    suspend(
        Session.objects.select_related("plan", "router", "operator").get(pk=session_id),
        new_status,
    )


@shared_task
def expire_sessions():
    """Beat task (every minute): cut off sessions past expires_at. The status flip
    uses a filtered UPDATE so concurrent beats can't double-fire the suspend."""
    from .models import Session

    expired = 0
    ids = list(
        Session.objects.filter(
            status=Session.Status.ACTIVE, expires_at__lte=timezone.now()
        ).values_list("id", flat=True)
    )
    for session_id in ids:
        flipped = Session.objects.filter(
            id=session_id, status=Session.Status.ACTIVE
        ).update(status=Session.Status.EXPIRED)
        if flipped:
            suspend_session.delay(session_id)
            expired += 1
    if expired:
        logger.info("Expired %d sessions", expired)
    return expired


@shared_task
def check_router_health():
    from .adapters import get_adapter
    from .models import Router, RouterHealthCheck

    for router in Router.objects.filter(is_active=True).exclude(management_host=""):
        was_online = router.status == Router.Status.ONLINE
        ok = False
        try:
            ok = get_adapter(router).test_connection()
        except Exception:
            logger.exception("Health check crashed for %s", router)
        RouterHealthCheck.objects.create(router=router, online=ok)
        router.mark_seen(ok)
        # Offline -> online transition: the router came back, re-sync its sessions
        if ok and not was_online and router.is_enrolled:
            sync_router.delay(router.id)


@shared_task
def sync_router(router_id: int):
    from .models import Router
    from .sync import sync_router_sessions

    router = Router.objects.get(pk=router_id)
    return sync_router_sessions(router)


@shared_task
def sync_all_routers():
    """Nightly safety net: reconcile every enrolled, active router."""
    from .models import Router

    for rid in Router.objects.filter(
        is_active=True, status=Router.Status.ONLINE
    ).exclude(management_host="").values_list("id", flat=True):
        sync_router.delay(rid)
