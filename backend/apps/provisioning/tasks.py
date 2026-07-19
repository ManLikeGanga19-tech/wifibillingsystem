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
    """Paid transaction -> session on the router.

    A PAID CUSTOMER MUST NEVER FALL INTO A VOID. The portal spins until it sees the
    connection succeed OR fail, so this task's contract is: on the final attempt, the
    transaction ends in a state the portal can read — an ACTIVE session, or a recorded
    failure. Never "paid, and nothing happened".

    Two failure shapes, both handled:
      - the session cannot even be CREATED (the ISP deleted their last router between
        the push and the callback): there is no session to mark, so the failure is
        recorded on the TRANSACTION.
      - the session is created but the router will not accept it (unreachable, tunnel
        down): the SESSION is marked FAILED.
    """
    from apps.payments.models import Transaction

    from . import services
    from .models import Router

    tx = Transaction.objects.select_related("plan", "operator", "subscriber", "router").get(
        pk=transaction_id
    )
    if tx.status not in Transaction.SUCCESS_STATUSES:
        logger.warning("provision_transaction called for non-paid tx %s (%s)", tx.pk, tx.status)
        return

    # Build the session. If there is no router at all, no session can exist (router is
    # PROTECT/non-null) — so the failure has to live on the transaction, or the portal
    # would poll a null session forever.
    try:
        session = services.create_session_for_transaction(tx)
    except Router.DoesNotExist as exc:
        _record_tx_provision_failure(tx, str(exc))
        logger.error("Tx %s paid but no router to provision onto: %s", tx.pk, exc)
        return  # nothing to retry — a router will not appear on its own

    try:
        services.activate(session)
        # Success clears any earlier failure note so a retry reads clean.
        if tx.provision_error:
            _record_tx_provision_failure(tx, "")
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # Final attempt. Record the failure and RETURN — do not re-raise. The
            # customer's state is now visible (session FAILED) and there is nothing
            # left to retry, so raising would only log a spurious task crash.
            session.status = session.Status.FAILED
            session.provision_error = str(exc)[:255]
            session.save(update_fields=["status", "provision_error", "updated_at"])
            logger.error("Session %s permanently failed to provision: %s", session.pk, exc)
            return
        raise  # earlier attempts: raise so Celery retries with backoff


def _record_tx_provision_failure(tx, message: str) -> None:
    tx.provision_error = message[:255]
    tx.save(update_fields=["provision_error", "updated_at"])


@shared_task(bind=True, **RETRY_KWARGS)
def activate_session(self, session_id: int):
    """Provision an already-created session (voucher redemptions, and retries of a
    failed hotspot session). Ends in a visible state: ACTIVE, or FAILED on the last
    attempt — never stuck PENDING, which the portal cannot tell from 'still trying'."""
    from .models import Session
    from .services import activate

    session = Session.objects.select_related("plan", "router", "operator").get(pk=session_id)
    try:
        activate(session)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            session.status = Session.Status.FAILED
            session.provision_error = str(exc)[:255]
            session.save(update_fields=["status", "provision_error", "updated_at"])
            logger.error("Session %s permanently failed to provision: %s", session.pk, exc)
            return
        raise


@shared_task(bind=True, **RETRY_KWARGS)
def suspend_session(self, session_id: int, new_status: str | None = None):
    from .models import Session
    from .services import suspend

    suspend(
        Session.objects.select_related("plan", "router", "operator").get(pk=session_id),
        new_status,
    )


@shared_task
def retry_failed_provisions():
    """Beat task: reconnect paid customers whose provisioning FAILED, once the router
    is likely back.

    A hotspot session is short-lived, so this only bothers with recent failures — an
    hour old at most. Beyond that the customer has given up and re-paying is cleaner
    than silently connecting someone who walked away an hour ago. The point is the
    common case: the router blinked for thirty seconds, five people paid during the
    outage, and they all reconnect on their own without a support call.
    """
    from datetime import timedelta

    from .models import Session

    cutoff = timezone.now() - timedelta(hours=1)
    stale = Session.objects.filter(
        status=Session.Status.FAILED,
        updated_at__gte=cutoff,
        expires_at__gt=timezone.now(),  # don't revive a window that has already closed
    ).values_list("id", flat=True)
    for session_id in list(stale):
        # Flip to PENDING so it is not picked up twice, then re-attempt.
        flipped = Session.objects.filter(
            id=session_id, status=Session.Status.FAILED
        ).update(status=Session.Status.PENDING)
        if flipped:
            activate_session.delay(session_id)


#: How long before expiry we text "your time is almost up". Long enough to act on
#: (find your phone, complete an STK push), short enough that they haven't wandered off.
EXPIRY_WARN_MINUTES = 10


@shared_task
def warn_expiring_sessions():
    """Text active customers a few minutes before their time runs out, so they can
    renew instead of just dropping offline. Each session is warned exactly once —
    guarded by expiry_warned_at, which activation resets on a fresh window."""
    from datetime import timedelta

    from apps.notifications.services import notify_expiring

    from .models import Session

    now = timezone.now()
    soon = now + timedelta(minutes=EXPIRY_WARN_MINUTES)
    due = Session.objects.filter(
        status=Session.Status.ACTIVE,
        expires_at__gt=now,
        expires_at__lte=soon,
        expiry_warned_at__isnull=True,
    ).select_related("operator", "plan", "subscriber")
    for session in due:
        # Claim it first (filtered UPDATE), so two overlapping beats can't double-text.
        claimed = Session.objects.filter(pk=session.pk, expiry_warned_at__isnull=True).update(
            expiry_warned_at=now
        )
        if claimed:
            notify_expiring(session)


#: Warn a capped customer once they've used this fraction of their data.
DATA_WARN_FRACTION = 0.9


@shared_task
def sync_hotspot_usage():
    """Pull live byte counters off each router into our sessions.

    The router already ENFORCES the data cap (limit-bytes-total cuts them off). This
    is so WE know the usage too — to warn a customer before they run dry, and to report
    on real consumption. Best-effort per router: one unreachable box must not stop the
    others."""
    from apps.notifications.services import notify_data_low

    from .adapters import get_adapter
    from .models import Router, Session

    router_ids = (
        Session.objects.filter(status=Session.Status.ACTIVE)
        .values_list("router_id", flat=True)
        .distinct()
    )
    for router in Router.objects.filter(id__in=list(router_ids), is_active=True):
        try:
            actives = {a.username: a for a in get_adapter(router).get_active_sessions()}
        except Exception:
            logger.warning("usage sync: %s unreachable", router.name)
            continue

        sessions = Session.objects.filter(
            router=router, status=Session.Status.ACTIVE
        ).select_related("plan", "operator", "subscriber")
        for session in sessions:
            live = actives.get(session.hotspot_username)
            if live is None:
                continue

            # First Wi-Fi login for a held (on-login) clock: the subscriber is connected
            # now, so start their window from this moment. Claim it with a filtered UPDATE
            # so two overlapping syncs can't start the clock twice.
            if not session.clock_started:
                now = timezone.now()
                started = Session.objects.filter(
                    pk=session.pk, clock_started=False
                ).update(
                    clock_started=True, starts_at=now, expires_at=now + session.plan.duration
                )
                if started:
                    session.clock_started = True
                    session.starts_at = now
                    session.expires_at = now + session.plan.duration

            used_mb = (live.bytes_in + live.bytes_out) // (1024 * 1024)
            if used_mb != session.data_used_mb:
                session.data_used_mb = used_mb
                session.save(update_fields=["data_used_mb", "updated_at"])

            cap = session.plan.data_cap_mb
            if cap and session.data_warned_at is None and used_mb >= cap * DATA_WARN_FRACTION:
                claimed = Session.objects.filter(
                    pk=session.pk, data_warned_at__isnull=True
                ).update(data_warned_at=timezone.now())
                if claimed:
                    notify_data_low(session)


@shared_task
def expire_sessions():
    """Beat task (every minute): cut off sessions past expires_at. The status flip
    uses a filtered UPDATE so concurrent beats can't double-fire the suspend."""
    from .models import Session

    expired = 0
    ids = list(
        Session.objects.filter(
            status=Session.Status.ACTIVE,
            clock_started=True,  # a held (on-login) clock hasn't begun — never expire it
            expires_at__lte=timezone.now(),
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
    from .adapters import ProvisioningAuthError, get_adapter
    from .models import Router, RouterHealthCheck
    from .outages import on_router_offline, on_router_online

    for router in Router.objects.filter(is_active=True).exclude(management_host=""):
        was_online = router.status == Router.Status.ONLINE
        was_offline = router.status == Router.Status.OFFLINE
        ok = False
        auth_failed = False
        try:
            ok = get_adapter(router).test_connection()
        except ProvisioningAuthError:
            auth_failed = True  # answered but rejected creds -> wiped/reset
        except Exception:
            logger.exception("Health check crashed for %s", router)
        RouterHealthCheck.objects.create(router=router, online=ok)
        _apply_reachability(router, ok, auth_failed)
        if ok:
            from .services import refresh_device_identity

            refresh_device_identity(router)  # keep version/model/serial current
        # Offline -> online transition with valid creds: re-sync its sessions.
        if ok and not was_online:
            sync_router.delay(router.id)

        # Operator alerts + outage compensation (Settings > Operator alerts). Only the real
        # edges fire: a router that was ONLINE and just dropped, or was OFFLINE and just
        # recovered. First contact (PENDING -> ONLINE) is neither a drop nor a recovery.
        if was_online and not ok:
            on_router_offline(router)
        elif was_offline and ok:
            on_router_online(router)


def _apply_reachability(router, ok: bool, auth_failed: bool):
    """Persist connection result: flag/clear onboarding_required, update status."""
    from .models import Router

    fields = ["status", "last_seen_at", "updated_at"]
    router.status = Router.Status.ONLINE if ok else Router.Status.OFFLINE
    if ok:
        router.last_seen_at = timezone.now()
        if router.onboarding_required:
            router.onboarding_required = False
            fields.append("onboarding_required")
    elif auth_failed and not router.onboarding_required:
        router.onboarding_required = True  # factory reset detected
        fields.append("onboarding_required")
    router.save(update_fields=fields)


@shared_task
def sync_router(router_id: int):
    from .models import Router
    from .sync import sync_router_sessions

    router = Router.objects.get(pk=router_id)
    return sync_router_sessions(router)


@shared_task
def sync_all_routers():
    """Nightly safety net: reconcile every reachable, online, active router."""
    from .models import Router

    for router in Router.objects.filter(is_active=True, status=Router.Status.ONLINE):
        if router.is_reachable:
            sync_router.delay(router.id)


@shared_task
def prune_dormant_hotspot_subscribers():
    """Beat task: delete hotspot customers unseen past the ISP's chosen window.
    Opt-in per operator (Settings > Hotspot); safe for the books — see hotspot_lifecycle."""
    from .hotspot_lifecycle import prune_dormant_subscribers

    return prune_dormant_subscribers()


@shared_task
def expire_unused_hotspot_vouchers():
    """Beat task: invalidate prepaid vouchers never sold inside the ISP's window.
    Opt-in per operator (voucher_expiry_days > 0); redeemed vouchers are never touched."""
    from apps.vouchers.services import expire_unused_vouchers

    return expire_unused_vouchers()
