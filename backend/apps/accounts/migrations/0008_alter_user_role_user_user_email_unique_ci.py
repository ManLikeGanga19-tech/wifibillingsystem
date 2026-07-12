"""ISP side collapses to one role, and email becomes a login identifier.

Order matters here: the data has to be made legal BEFORE the constraints that will
police it. Retire the two tenant sub-roles onto their rows, canonicalise every email
to lowercase, and only then add the case-insensitive unique index — otherwise an ISP
who typed Ann@acme.co.ke takes the migration down on a live database.
"""

import django.db.models.functions.text
from django.db import migrations, models
from django.db.models.functions import Lower


def retire_tenant_sub_roles(apps, schema_editor):
    """tenant_manager / tenant_support -> tenant_owner.

    Both were ISP-side logins that already had access to that ISP's console; the only
    thing they gain is the ability to move the ISP's own money — which is that ISP's
    business, not ours, and there is no other role left for them to hold. Leaving them
    on a value the enum no longer knows about would be worse: silent rows that no
    permission check matches.
    """
    User = apps.get_model("accounts", "User")
    User.objects.filter(role__in=["tenant_manager", "tenant_support"]).update(
        role="tenant_owner"
    )


def canonicalise_emails(apps, schema_editor):
    """One casing, one account. Refuses rather than mangles if two rows collide."""
    from django.db.models import Count

    User = apps.get_model("accounts", "User")
    clashes = (
        User.objects.exclude(email="")
        .annotate(lowered=Lower("email"))
        .values("lowered")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    if clashes:
        addresses = ", ".join(c["lowered"] for c in clashes)
        raise RuntimeError(
            "Two accounts share an email address (case-insensitively): "
            f"{addresses}. Email is a login identifier now, so this must be resolved "
            "by a human — pick which account keeps it before migrating."
        )
    User.objects.exclude(email="").update(email=Lower("email"))


def noop(apps, schema_editor):
    """Both data steps are safe to leave in place on the way back down."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_assign_roles"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0013_operator_change_code_attempts_and_more"),
    ]

    operations = [
        migrations.RunPython(retire_tenant_sub_roles, noop),
        migrations.RunPython(canonicalise_emails, noop),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("platform_owner", "Platform owner"),
                    ("platform_support", "Platform support (read-only)"),
                    ("tenant_owner", "ISP owner"),
                ],
                db_index=True,
                default="tenant_owner",
                max_length=20,
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                condition=models.Q(("email", ""), _negated=True),
                name="user_email_unique_ci",
            ),
        ),
    ]
