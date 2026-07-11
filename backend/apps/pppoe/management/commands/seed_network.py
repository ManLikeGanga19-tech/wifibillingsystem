"""Seed a realistic PPPoE wireless topology so the Network UI can be exercised in
EVERY capacity scenario: empty, healthy, near-full, over-subscribed, unset
capacity, and a 1:1 PTP link. Idempotent — safe to re-run.

    docker compose exec api python manage.py seed_network
    docker compose exec api python manage.py seed_network --operator myisp

Utilization (AccessPointSerializer): round(100 * active_clients / capacity),
or null when capacity is unset (0). Clients in ACTIVE or SUSPENDED count.
"""

import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction as db_transaction

from apps.core.models import Operator
from apps.pppoe.models import (
    AccessPoint,
    Client,
    ServicePlan,
    Tower,
    generate_account_number,
)
from apps.provisioning.models import Router

# Two broadband packages so demo clients aren't all on one plan.
PLANS = [
    {
        "name": "Home 8Mbps",
        "price": 1500,
        "download_kbps": 8192,
        "upload_kbps": 4096,
        "mikrotik_profile": "wifios-home-8m",
        "sort_order": 1,
    },
    {
        "name": "Biz 20Mbps",
        "price": 3500,
        "download_kbps": 20480,
        "upload_kbps": 10240,
        "mikrotik_profile": "wifios-biz-20m",
        "sort_order": 2,
    },
]

# Each AP scenario: (tower, ap_name, mode, band, capacity, active, suspended,
# pending, delivery). active+suspended count toward utilization; pending does not.
# fmt: off
TOPOLOGY = [
    # "Nyeri Hill" — a busy PTMP mast spanning the full utilization range:
    ("Nyeri Hill", "Sector North", "ptmp", "5GHz", 30, 12, 0, 2, "wireless_ptmp"),  # ~40% healthy
    ("Nyeri Hill", "Sector South", "ptmp", "5GHz", 20, 15, 2, 0, "wireless_ptmp"),  # 85% near-full
    ("Nyeri Hill", "Sector East",  "ptmp", "5GHz", 15, 14, 2, 0, "wireless_ptmp"),  # 107% over
    ("Nyeri Hill", "Sector West",  "ptmp", "5GHz", 25, 0,  0, 0, "wireless_ptmp"),  # 0% empty
    # "Kagumo Ridge" — backhaul PTP + a legacy AP with no capacity set:
    ("Kagumo Ridge", "PTP to Nyeri", "ptp", "5GHz", 1, 1, 0, 0, "wireless_ptp"),    # 100% link
    ("Kagumo Ridge", "Legacy 2.4",   "ap",  "2.4GHz", 0, 5, 1, 0, "wireless_ptmp"),  # unset -> null
    # "Town Centre" — fibre/ethernet distribution POP:
    ("Town Centre", "Fibre POP", "ap", "", 40, 8, 0, 1, "fibre"),                   # 20% roomy
]
# fmt: on


class Command(BaseCommand):
    help = "Seed a demo PPPoE topology covering all tower/AP capacity scenarios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            default="default",
            help="Operator slug to seed under (default: 'default').",
        )

    def handle(self, *args, **options):
        slug = options["operator"]
        try:
            operator = Operator.objects.get(slug=slug)
        except Operator.DoesNotExist as exc:
            raise CommandError(
                f"No operator with slug '{slug}'. Run seed_dev first or pass --operator."
            ) from exc

        plans = self._ensure_plans(operator)
        router = self._ensure_router(operator)

        created_clients = 0
        for tname, apname, mode, band, cap, n_active, n_susp, n_pending, delivery in TOPOLOGY:
            tower, _ = Tower.objects.get_or_create(
                operator=operator, name=tname, defaults={"is_active": True}
            )
            ap, _ = AccessPoint.objects.get_or_create(
                operator=operator,
                tower=tower,
                name=apname,
                defaults={
                    "mode": mode,
                    "band": band,
                    "capacity": cap,
                    "router": router,
                    "ssid": f"{operator.slug}-{apname}".replace(" ", "-").lower(),
                },
            )
            # Keep capacity/mode in sync if the AP already existed
            if ap.capacity != cap or ap.mode != mode:
                ap.capacity, ap.mode = cap, mode
                ap.save(update_fields=["capacity", "mode", "updated_at"])

            created_clients += self._fill(
                operator, router, plans, ap, delivery,
                Client.Status.ACTIVE, n_active,
            )
            created_clients += self._fill(
                operator, router, plans, ap, delivery,
                Client.Status.SUSPENDED, n_susp,
            )
            created_clients += self._fill(
                operator, router, plans, ap, delivery,
                Client.Status.PENDING_INSTALL, n_pending,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Network seeded for '{operator.slug}': "
                f"{Tower.objects.filter(operator=operator).count()} towers, "
                f"{AccessPoint.objects.filter(operator=operator).count()} APs, "
                f"+{created_clients} demo clients."
            )
        )
        self.stdout.write(
            "Scenarios: healthy 40%, near-full 85%, over-subscribed 107%, "
            "empty 0%, PTP 100%, capacity-unset (null), fibre POP 20%."
        )

    # -- helpers -------------------------------------------------------------

    def _ensure_plans(self, operator):
        plans = []
        for spec in PLANS:
            plan, _ = ServicePlan.objects.get_or_create(
                operator=operator, name=spec["name"], defaults=spec
            )
            plans.append(plan)
        return plans

    def _ensure_router(self, operator):
        router, _ = Router.objects.get_or_create(
            operator=operator,
            name="Demo PPPoE Router (dummy)",
            defaults={
                "management_host": "127.0.0.1",
                "provisioning_backend": Router.Backend.DUMMY,
            },
        )
        return router

    def _fill(self, operator, router, plans, ap, delivery, status, target):
        """Create clients on `ap` with `status` until it has `target` of them.
        Idempotent: counts what's already there so re-runs don't pile up."""
        have = Client.objects.filter(access_point=ap, status=status).count()
        made = 0
        for i in range(have, target):
            plan = plans[i % len(plans)]
            with db_transaction.atomic():
                account = generate_account_number(operator)
                Client.objects.create(
                    operator=operator,
                    account_number=account,
                    full_name=f"{ap.name} Client {i + 1}",
                    phone="2547" + "".join(secrets.choice("0123456789") for _ in range(8)),
                    plan=plan,
                    router=router,
                    access_point=ap,
                    delivery_method=delivery,
                    pppoe_username=account.lower(),
                    pppoe_password=secrets.token_urlsafe(9),
                    status=status,
                    billing_day=((i % 28) + 1),
                )
            made += 1
        return made
