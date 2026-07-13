"""Give every EXISTING ISP their welcome credits.

The grant fires on operator creation (see signals.py), which does nothing for the ISPs who
already existed when credits were introduced. Without this they would open Settings, see a
balance of zero, and their receipts would stop — a regression handed to the very tenants
who have been with us longest.

Idempotent: skips any operator that already has a credit entry.
"""

from django.db import migrations


def grant(apps, schema_editor):
    Operator = apps.get_model("core", "Operator")
    SmsCreditEntry = apps.get_model("notifications", "SmsCreditEntry")

    # Frozen at the value this migration was written with. A migration must NEVER import
    # live app code: `notifications.credits` has since been deleted (credits became KES on
    # the platform account), and importing it would make this historical migration
    # un-runnable on a fresh database — which is how a project loses the ability to rebuild
    # itself from scratch.
    WELCOME_CREDITS = 250

    already = set(SmsCreditEntry.objects.values_list("operator_id", flat=True))
    SmsCreditEntry.objects.bulk_create(
        [
            SmsCreditEntry(
                operator=operator,
                credits=WELCOME_CREDITS,
                reason="grant",
                memo="Welcome credits",
            )
            for operator in Operator.objects.exclude(pk__in=already)
        ]
    )


def ungrant(apps, schema_editor):
    SmsCreditEntry = apps.get_model("notifications", "SmsCreditEntry")
    SmsCreditEntry.objects.filter(reason="grant", memo="Welcome credits").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0006_remove_messagingsettings_sms_api_key_and_more"),
        ("core", "0001_initial"),
    ]

    operations = [migrations.RunPython(grant, ungrant)]
