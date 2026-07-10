from celery import shared_task


@shared_task
def charge_monthly_base_fees():
    from .services import charge_monthly_base_fees as run

    return run()
