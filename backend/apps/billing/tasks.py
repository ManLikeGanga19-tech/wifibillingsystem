from celery import shared_task


@shared_task
def charge_monthly_base_fees():
    from .services import charge_monthly_base_fees as run

    return run()


@shared_task
def charge_pppoe_user_fees():
    from .services import charge_pppoe_user_fees as run

    return run()


@shared_task
def reconcile_pending_topups():
    """The safety net for a top-up callback that never arrived.

    Safaricom drops callbacks. Without this an ISP who has genuinely paid sits on a spinner
    and their SMS stays switched off — we would be holding their money AND withholding the
    service. Same pattern (and same hard-won lesson) as the subscriber payment reconciler.
    """
    from django.utils import timezone

    from .models import TopUp
    from .topup import MAX_RECONCILE_ATTEMPTS, RECONCILE_AFTER_SECONDS, reconcile

    cutoff = timezone.now() - timezone.timedelta(seconds=RECONCILE_AFTER_SECONDS)
    stale = TopUp.objects.filter(
        status=TopUp.Status.PENDING,
        created_at__lte=cutoff,
        reconcile_attempts__lt=MAX_RECONCILE_ATTEMPTS,
        checkout_request_id__isnull=False,
    )
    for row in stale:
        reconcile(row)

    # Give up on the truly dead ones so they stop being polled forever, and so the console
    # can stop spinning and say something honest.
    TopUp.objects.filter(
        status=TopUp.Status.PENDING,
        reconcile_attempts__gte=MAX_RECONCILE_ATTEMPTS,
    ).update(status=TopUp.Status.TIMEOUT, result_desc="No response from M-Pesa")
    return stale.count()
