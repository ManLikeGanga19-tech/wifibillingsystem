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


@shared_task
def warn_past_due_operators():
    """Text an ISP the moment they cross the WARN line — before new sales stop.

    Once per fall, re-armed when they recover, exactly like the low-SMS-balance alert. The
    warning SMS is a platform ALERT, so it is never billed to the balance it is warning
    about (and it must get through even when they owe us).
    """
    from django.utils import timezone

    from apps.billing import enforcement as enf
    from apps.core.models import Operator
    from apps.notifications.models import Message
    from apps.notifications.services import send_sms

    warned = 0
    # Only tenants that can actually owe — skip the platform's own WISP.
    for operator in Operator.objects.filter(is_platform_owned=False, is_active=True):
        level = enf.billing_level(operator)
        past_warn = level in (enf.WARNED, enf.RESTRICTED, enf.LOCKED)

        if not past_warn:
            # Recovered — re-arm so the next fall warns again.
            if operator.billing_warned_at:
                operator.billing_warned_at = None
                operator.save(update_fields=["billing_warned_at", "updated_at"])
            continue

        if operator.billing_warned_at:
            continue  # already told them about this fall

        owed = enf.amount_owed(operator)
        phone = operator.contact_phone
        if phone:
            if level == enf.LOCKED:
                body = (
                    f"WIFI.OS: your account is past due (KSh {owed:,.0f}) and your console is "
                    "now read-only. Pay in Settings > Payments to restore full access."
                )
            elif level == enf.RESTRICTED:
                body = (
                    f"WIFI.OS: you owe KSh {owed:,.0f}. New sales are paused until you pay — "
                    "existing customers are unaffected. Settle in Settings > Payments."
                )
            else:
                body = (
                    f"WIFI.OS: you owe KSh {owed:,.0f}. Top up in Settings > Payments before "
                    "new sales are paused."
                )
            send_sms(operator, phone, body, category=Message.Category.ALERT)

        operator.billing_warned_at = timezone.now()
        operator.save(update_fields=["billing_warned_at", "updated_at"])
        warned += 1

    return warned
