"""Every new ISP starts with SMS that works.

The managed gateway is prepaid, and a prepaid balance of zero would mean a brand-new ISP
makes their first sale and the customer gets no receipt — which is precisely the failure
the managed gateway exists to prevent. So an operator is granted a small welcome balance
the moment they exist: enough to run a pilot and see the value, small enough that a real
business tops up quickly.

It is a real ledger entry, not a special case in the balance calculation — the books
always explain themselves.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import Operator

from .credits import WELCOME_CREDITS
from .models import SmsCreditEntry


@receiver(post_save, sender=Operator, dispatch_uid="grant_welcome_sms_credits")
def grant_welcome_credits(sender, instance, created, **kwargs):
    if not created or WELCOME_CREDITS <= 0:
        return
    SmsCreditEntry.objects.create(
        operator=instance,
        credits=WELCOME_CREDITS,
        reason=SmsCreditEntry.Reason.GRANT,
        memo="Welcome credits",
    )
