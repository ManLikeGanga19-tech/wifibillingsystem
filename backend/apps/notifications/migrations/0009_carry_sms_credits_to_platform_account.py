"""Move every ISP's SMS credit balance onto the new shilling-denominated account.

SMS credits used to be an integer counter bought out of the WALLET. They are now KES on
the platform account, because an ISP selling through their OWN gateway has no wallet
balance to buy credits with — yet still owes us for every SMS we send on their behalf.

Dropping SmsCreditEntry without this would silently zero the balance of every ISP who had
paid for credits. So the balance is converted at the price those credits are worth and
recorded as a single GRANT, which leaves the new ledger able to explain where the money
came from.

Runs BEFORE the table is dropped. Order is the whole point.
"""

from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def carry_credits_across(apps, schema_editor):
    SmsCreditEntry = apps.get_model("notifications", "SmsCreditEntry")
    PlatformLedgerEntry = apps.get_model("billing", "PlatformLedgerEntry")
    Operator = apps.get_model("core", "Operator")

    # Frozen, deliberately: a migration must not import live app code. If the SMS price
    # changes tomorrow, the shillings we credited people yesterday must not change with it.
    SMS_PRICE = Decimal("0.80")

    balances = (
        SmsCreditEntry.objects.values("operator")
        .annotate(credits=Sum("credits"))
        .filter(credits__gt=0)
    )
    by_id = {row["operator"]: row["credits"] for row in balances}
    if not by_id:
        return

    operators = Operator.objects.in_bulk(list(by_id))
    PlatformLedgerEntry.objects.bulk_create(
        [
            PlatformLedgerEntry(
                operator=operators[op_id],
                amount=(Decimal(credits) * SMS_PRICE).quantize(Decimal("0.01")),
                reason="grant",
                memo=f"Carried over from {credits:,} SMS credits",
            )
            for op_id, credits in by_id.items()
            if op_id in operators
        ]
    )


def uncarry(apps, schema_editor):
    PlatformLedgerEntry = apps.get_model("billing", "PlatformLedgerEntry")
    PlatformLedgerEntry.objects.filter(memo__startswith="Carried over from").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0008_messagingsettings_alert_phones_and_more"),
        # The new account must EXIST before we can move balances onto it.
        ("billing", "0009_topup_platformledgerentry"),
    ]

    operations = [
        migrations.RunPython(carry_credits_across, uncarry),
        migrations.DeleteModel(name="SmsCreditEntry"),
    ]
