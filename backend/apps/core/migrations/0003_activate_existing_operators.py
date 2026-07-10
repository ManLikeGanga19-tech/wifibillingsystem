"""Existing operators predate the approval flow — grandfather them in as active."""

from django.db import migrations
from django.utils import timezone


def activate_existing(apps, schema_editor):
    Operator = apps.get_model("core", "Operator")
    Operator.objects.filter(status="pending").update(
        status="active", approved_at=timezone.now()
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_operator_approved_at_operator_base_fee_and_more"),
    ]

    operations = [
        migrations.RunPython(activate_existing, migrations.RunPython.noop),
    ]
