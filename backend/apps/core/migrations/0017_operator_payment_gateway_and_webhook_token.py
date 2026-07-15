"""Which gateway an ISP collects through, and the secret in their payment webhook URL.

The token cannot simply be added as a unique column: Django would write ONE default into
every existing row and the unique index would refuse to build. So it goes in three steps —
add it nullable, mint a distinct token per operator, then enforce uniqueness. That is also
the only order that is safe to run against a live database with tenants already in it.
"""

import secrets

from django.db import migrations, models

import apps.core.models


def mint_tokens(apps, schema_editor):
    Operator = apps.get_model("core", "Operator")
    for operator in Operator.objects.filter(webhook_token=""):
        # Frozen here rather than imported (a migration must not depend on live app code).
        operator.webhook_token = secrets.token_urlsafe(18)[:24]
        operator.save(update_fields=["webhook_token"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_operator_previous_slug_operator_slug_changed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="payment_gateway",
            field=models.CharField(default="wifios", max_length=20),
        ),
        migrations.AddField(
            model_name="operator",
            name="webhook_token",
            field=models.CharField(default="", editable=False, max_length=32),
        ),
        migrations.RunPython(mint_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="operator",
            name="webhook_token",
            field=models.CharField(
                default=apps.core.models._webhook_token,
                editable=False,
                max_length=32,
                unique=True,
            ),
        ),
    ]
