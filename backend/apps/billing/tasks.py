from celery import shared_task


@shared_task
def charge_monthly_base_fees():
    from .services import charge_monthly_base_fees as run

    return run()


@shared_task
def charge_pppoe_user_fees():
    from .services import charge_pppoe_user_fees as run

    return run()
