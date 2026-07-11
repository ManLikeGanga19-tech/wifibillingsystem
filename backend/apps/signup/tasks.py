from celery import shared_task


@shared_task
def sweep_expired_signups():
    """Abandoned drafts expire rather than rot. Nothing half-finished should
    outlive its usefulness — least of all a record holding someone's email."""
    from .services import sweep_expired

    return sweep_expired()
