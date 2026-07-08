"""Seed local development data: operator, plans, a dummy router, and an admin login."""

from datetime import timedelta

from django.core.management.base import BaseCommand

from apps.accounts.models import User
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
            slug="default", defaults={"name": "My WISP"}
        )
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

        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(
                phone="254700000000", password="admin12345", name="Dev Admin", operator=operator
            )
            self.stdout.write(
                self.style.WARNING(
                    "Superuser created -> phone: 254700000000  password: admin12345 (DEV ONLY)"
                )
            )
        self.stdout.write(self.style.SUCCESS("Seed complete."))
