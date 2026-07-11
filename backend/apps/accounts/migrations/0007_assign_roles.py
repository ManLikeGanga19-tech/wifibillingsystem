"""Assign RBAC roles to pre-existing login accounts.

Before this, capability was implied by `is_superuser` + "has no operator", which
made the platform hat and the ISP hat mutually exclusive and caused a
cross-tenant data leak. Roles are now explicit.
"""

from django.db import migrations


def assign_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    # Superusers become platform owners (they may also keep a home ISP).
    User.objects.filter(is_superuser=True).update(role="platform_owner")
    # Everyone else who can log into a console owns their ISP until told otherwise.
    User.objects.filter(is_superuser=False, is_staff=True).update(role="tenant_owner")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_user_role_alter_user_operator"),
    ]

    operations = [
        migrations.RunPython(assign_roles, migrations.RunPython.noop),
    ]
