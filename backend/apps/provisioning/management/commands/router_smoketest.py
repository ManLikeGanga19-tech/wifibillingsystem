"""Non-destructive connectivity + capability check for real routers. Point it at
each hardware model before staging to confirm the adapter talks to it.

    docker compose exec api python manage.py router_smoketest            # all active
    docker compose exec api python manage.py router_smoketest --router 3
    docker compose exec api python manage.py router_smoketest --operator myisp

Read-only: it authenticates, reads board/version/health, and counts live
hotspot + PPPoE sessions. It never creates, changes, or deletes anything on the
router, so it is safe to run against production devices.
"""

from django.core.management.base import BaseCommand

from apps.provisioning.adapters import (
    ProvisioningAuthError,
    ProvisioningError,
    get_adapter,
)
from apps.provisioning.models import Router


class Command(BaseCommand):
    help = "Read-only connectivity/capability check against real routers."

    def add_arguments(self, parser):
        parser.add_argument("--router", type=int, help="Check one router by id.")
        parser.add_argument("--operator", help="Limit to one operator slug.")

    def handle(self, *args, **options):
        routers = Router.objects.filter(is_active=True).select_related("operator")
        if options.get("router"):
            routers = routers.filter(pk=options["router"])
        if options.get("operator"):
            routers = routers.filter(operator__slug=options["operator"])
        routers = list(routers.order_by("operator__slug", "name"))

        if not routers:
            self.stdout.write(self.style.WARNING("No matching active routers."))
            return

        passed = 0
        for r in routers:
            ok = self._check(r)
            passed += 1 if ok else 0

        self.stdout.write("")
        summary = f"{passed}/{len(routers)} routers passed."
        style = self.style.SUCCESS if passed == len(routers) else self.style.WARNING
        self.stdout.write(style(summary))

    def _check(self, router) -> bool:
        header = f"[{router.operator.slug}] {router.name} ({router.management_host})"
        self.stdout.write(self.style.HTTP_INFO(header))
        adapter = get_adapter(router)

        # 1) Auth + reachability
        try:
            if not adapter.test_connection():
                self.stdout.write(self.style.ERROR("  ✗ connection: rejected"))
                return False
        except ProvisioningAuthError:
            self.stdout.write(
                self.style.ERROR("  ✗ auth: credentials rejected — router needs re-onboarding")
            )
            return False
        except ProvisioningError as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ unreachable: {exc}"))
            return False
        self.stdout.write("  ✓ connection ok")

        # 2) Device identity + health
        try:
            info = adapter.get_device_info()
            self.stdout.write(
                f"    board={info.board_name or '?'} "
                f"ros={info.routeros_version or '?'} "
                f"arch={info.architecture or '?'} "
                f"serial={info.serial_number or '?'}"
            )
            health = []
            if info.cpu_load is not None:
                health.append(f"cpu={info.cpu_load}%")
            if info.uptime:
                health.append(f"uptime={info.uptime}")
            if info.free_memory is not None and info.total_memory:
                used = 100 - round(100 * info.free_memory / info.total_memory)
                health.append(f"mem={used}%")
            if health:
                self.stdout.write("    " + " ".join(health))
        except ProvisioningError as exc:
            self.stdout.write(self.style.WARNING(f"  ! device info unavailable: {exc}"))

        # 3) Live sessions (hotspot + PPPoE) — proves the adapter can read state
        try:
            hotspot = len(adapter.get_active_sessions())
            self.stdout.write(f"  ✓ hotspot active sessions: {hotspot}")
        except ProvisioningError as exc:
            self.stdout.write(self.style.WARNING(f"  ! hotspot read failed: {exc}"))
        try:
            pppoe = len(adapter.get_active_pppoe())
            self.stdout.write(f"  ✓ PPPoE active sessions: {pppoe}")
        except ProvisioningError as exc:
            self.stdout.write(self.style.WARNING(f"  ! PPPoE read failed: {exc}"))

        return True
