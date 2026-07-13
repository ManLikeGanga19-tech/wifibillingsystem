"""Every new ISP starts with SMS that works.

The managed gateway is prepaid, and a balance of zero would mean a brand-new ISP makes
their first sale and the customer gets no receipt — precisely the failure the managed
gateway exists to prevent. So an operator is granted a small welcome balance the moment
they exist: enough to run a pilot and see the value, small enough that a real business
tops up quickly.

It is a real ledger entry, not a special case in the balance calculation — the books
always explain themselves.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import Operator


@receiver(post_save, sender=Operator, dispatch_uid="grant_welcome_sms_credits")
def grant_welcome_credits(sender, instance, created, **kwargs):
    from apps.billing.platform_account import WELCOME_CREDIT, grant

    if not created or WELCOME_CREDIT <= 0:
        return
    grant(instance, WELCOME_CREDIT, memo="Welcome credit")
