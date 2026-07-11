"""Delete the legacy customer rows from the User table.

Customers now live in accounts.Subscriber (backfilled in 0004). The leftover
passwordless, non-staff User rows are no longer referenced by anything — and if
left behind they would still occupy their phone number in the globally-unique
User.phone index, which is precisely the bug this refactor removes (a customer's
phone could never register an ISP account).

Only rows that are neither staff nor superuser are removed: real login accounts
are untouched.
"""

from django.db import migrations


def purge_customer_users(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_staff=False, is_superuser=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_backfill_subscribers"),
    ]

    operations = [
        migrations.RunPython(purge_customer_users, migrations.RunPython.noop),
    ]
