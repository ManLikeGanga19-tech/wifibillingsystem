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

        self._map_geodata(operator, router)

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
        # The delegated ISP workforce — one login per role so you can click the console as
        # each of them. All on the same dev operator, all admin12345.
        for phone, name, role in (
            ("254700000004", "Amina (Admin)", Role.TENANT_ADMIN),
            ("254700000005", "Care Desk", Role.TENANT_CARE),
            ("254700000006", "Field Technician", Role.TENANT_TECHNICIAN),
        ):
            if not User.objects.filter(phone=phone).exists():
                User.objects.create_user(
                    phone=phone, password="admin12345", name=name,
                    operator=operator, role=role, is_staff=True,
                )
                self.stdout.write(f"{role.label} -> {phone} / admin12345 (DEV ONLY)")
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _map_geodata(self, operator, router):
        """Give the dev operator geolocated towers, routers and PPPoE clients so the Map page
        has something real when you log in at localhost:4600. Idempotent + Nairobi-based."""
        import random
        from decimal import Decimal

        from apps.ops.models import Lead
        from apps.pppoe.models import Client, ServicePlan, Tower

        rng = random.Random(7)
        # Place the existing dummy router, add one more (offline, to show status colour).
        router.gps_lat, router.gps_lng, router.status = Decimal("-1.2921"), Decimal("36.8219"), \
            router.Status.ONLINE
        router.save(update_fields=["gps_lat", "gps_lng", "status", "updated_at"])
        Router.objects.get_or_create(
            operator=operator, name="Westlands Site",
            defaults={"management_host": "10.10.0.2", "provisioning_backend": Router.Backend.DUMMY,
                      "gps_lat": Decimal("-1.2650"), "gps_lng": Decimal("36.8030"),
                      "status": Router.Status.OFFLINE},
        )
        for name, lat, lng in [("CBD Tower", "-1.2860", "36.8230"),
                               ("Kilimani Tower", "-1.2900", "36.7850")]:
            Tower.objects.get_or_create(
                operator=operator, name=name,
                defaults={"gps_lat": Decimal(lat), "gps_lng": Decimal(lng)},
            )
        plan, _ = ServicePlan.objects.get_or_create(
            operator=operator, name="Dev Home 10Mbps",
            defaults={"price": Decimal("2500"), "download_kbps": 10240, "upload_kbps": 5120,
                      "mikrotik_profile": "dev-home-10"},
        )
        if Client.objects.filter(operator=operator).count() < 12:
            statuses = ([Client.Status.ACTIVE] * 8 + [Client.Status.SUSPENDED] * 2
                        + [Client.Status.CANCELLED])
            for i, st in enumerate(statuses):
                Client.objects.get_or_create(
                    operator=operator, account_number=f"DEV{i + 1:04d}",
                    defaults={
                        "full_name": f"Dev Client {i + 1}",
                        "phone": f"2547{rng.randint(10**7, 10**8 - 1)}",
                        "plan": plan, "router": router, "status": st,
                        "pppoe_username": f"dev-{i + 1}", "pppoe_password": "devpass123",
                        "billing_day": 1,
                        "gps_lat": Decimal(str(round(-1.29 + rng.uniform(-0.03, 0.03), 6))),
                        "gps_lng": Decimal(str(round(36.81 + rng.uniform(-0.03, 0.03), 6))),
                    },
                )
        # Leads in two demand clusters, so the Map's heatmap has hotspots.
        if Lead.objects.filter(operator=operator).count() < 10:
            spots = [(-1.300, 36.780), (-1.270, 36.805)]
            for i in range(12):
                hs = spots[i % 2]
                Lead.objects.get_or_create(
                    operator=operator, name=f"Dev Lead {i + 1}",
                    defaults={
                        "phone": f"2547{rng.randint(10**7, 10**8 - 1)}",
                        "location": "Nairobi",
                        "status": rng.choice([Lead.Status.NEW, Lead.Status.NEW,
                                              Lead.Status.CONTACTED]),
                        "gps_lat": Decimal(str(round(hs[0] + rng.uniform(-0.01, 0.01), 6))),
                        "gps_lng": Decimal(str(round(hs[1] + rng.uniform(-0.01, 0.01), 6))),
                    },
                )
        self.stdout.write("Map geodata seeded for the dev operator")
