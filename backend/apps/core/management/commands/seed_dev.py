"""Seed local development data: operator, plans, a dummy router, and an admin login."""

from datetime import timedelta

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User
from apps.core.models import Operator
from apps.plans.models import Plan
from apps.provisioning.models import Router

PLANS = [
    ("1 Hour Express", 20, timedelta(hours=1), 5120, 2048, 1),
    ("3 Hours Standard", 50, timedelta(hours=3), 3072, 1024, 1),
    ("Daily Unlimited", 100, timedelta(days=1), 5120, 2048, 1),
    ("Weekly Premium", 350, timedelta(days=7), 6144, 3072, 2),
    ("Monthly Home", 2000, timedelta(days=30), 10240, 5120, 3),
]


class Command(BaseCommand):
    help = "Seed development data (idempotent)"

    def handle(self, *args, **options):
        operator, created = Operator.objects.get_or_create(
            slug="default",
            defaults={"name": "My WISP", "status": Operator.Status.ACTIVE},
        )
        if operator.status != Operator.Status.ACTIVE:
            operator.status = Operator.Status.ACTIVE
            operator.save(update_fields=["status", "updated_at"])
        self.stdout.write(f"Operator: {operator.name} ({'created' if created else 'exists'})")

        for name, price, duration, down, up, shared in PLANS:
            plan, created = Plan.objects.get_or_create(
                operator=operator,
                name=name,
                defaults={
                    "price": price,
                    "duration": duration,
                    "download_kbps": down,
                    "upload_kbps": up,
                    "shared_users": shared,
                },
            )
            if created:
                self.stdout.write(f"Plan created: {plan}")

        router, created = Router.objects.get_or_create(
            operator=operator,
            name="Dev Router (dummy)",
            defaults={
                "management_host": "127.0.0.1",
                "provisioning_backend": Router.Backend.DUMMY,
            },
        )
        if created:
            self.stdout.write("Dummy router created")

        # The platform owner ALSO runs his own WISP: one login, two hats.
        # That tenant is platform-owned, so it pays no commission or fees.
        if not operator.is_platform_owned:
            operator.is_platform_owned = True
            operator.save(update_fields=["is_platform_owned", "updated_at"])
            self.stdout.write("Default operator marked platform-owned (fee exempt)")

        owner = User.objects.filter(phone="254700000000").first()
        if owner is None:
            User.objects.create_superuser(
                phone="254700000000",
                password="admin12345",
                name="Daniel (Platform Owner)",
                operator=operator,
                role=Role.PLATFORM_OWNER,
            )
        else:
            # Keep the dev owner in the intended shape (both hats, own WISP)
            owner.role = Role.PLATFORM_OWNER
            owner.operator = operator
            owner.save(update_fields=["role", "operator"])
        self.stdout.write(
            self.style.WARNING(
                "PLATFORM OWNER + ISP owner -> 254700000000 / admin12345 (DEV ONLY)"
            )
        )
        # Read-only PLATFORM support: the hat we actually use (troubleshooting an ISP
        # without the power to change anything). The ISP side has one role — owner —
        # so there are no sub-role logins left to seed.
        if not User.objects.filter(phone="254700000003").exists():
            User.objects.create_user(
                phone="254700000003",
                password="admin12345",
                name="Platform Support",
                email="support@danamo.co.ke",
                role=Role.PLATFORM_SUPPORT,
                is_staff=True,
            )
            self.stdout.write(
                "Platform support -> 254700000003 / admin12345 (read-only, "
                "or sign in with support@danamo.co.ke)"
            )
        self.stdout.write(self.style.SUCCESS("Seed complete."))
