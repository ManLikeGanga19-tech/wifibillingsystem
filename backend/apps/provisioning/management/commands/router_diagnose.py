"""Read-only 'why are my clients slow?' diagnostic for a router.

Pulls the signals behind a slow-speed complaint straight from the router and cross-checks
them against what WIFI.OS has sold, then flags the likely cause. It NEVER changes anything
on the router, so it is safe to run against production — ideally AT PEAK (evening), because
contention and CPU saturation only show under load.

    docker compose exec api python manage.py router_diagnose --router 3
    docker compose exec api python manage.py router_diagnose --operator myisp
    docker compose exec api python manage.py router_diagnose --uplink 100   # your WAN Mbps

Checks, mapped to the hypotheses:
  * CPU / memory         -> the RB951 pegged at peak (everything slows)
  * MSS clamp present?    -> the classic PPPoE 'pages half-load / HTTPS crawls'
  * sold vs uplink Mbps   -> oversubscription / peak-hour contention
  * simple-queue sanity   -> a client double-limited by a leftover /queue/simple
  * live WAN throughput   -> is the uplink pinned at its ceiling right now
"""

from django.core.management.base import BaseCommand

from apps.provisioning.adapters import (
    ProvisioningAuthError,
    ProvisioningError,
    get_adapter,
)
from apps.provisioning.models import Router

CPU_WARN = 80  # % — a MIPS board above this under load is the bottleneck
MEM_WARN = 85


class Command(BaseCommand):
    help = "Read-only slow-speed diagnostic against a router (safe on production)."

    def add_arguments(self, parser):
        parser.add_argument("--router", type=int, help="Diagnose one router by id.")
        parser.add_argument("--operator", help="Limit to one operator slug.")
        parser.add_argument(
            "--uplink", type=float, default=None,
            help="Your WAN uplink in Mbps, to compute the oversubscription ratio.",
        )

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

        for r in routers:
            self._diagnose(r, uplink=options.get("uplink"))

    def _diagnose(self, router, *, uplink):
        from apps.pppoe.models import Client

        self.stdout.write(self.style.HTTP_INFO(
            f"\n[{router.operator.slug}] {router.name} ({router.management_host})"
        ))
        try:
            diag = get_adapter(router).get_speed_diagnostics()
        except ProvisioningAuthError:
            self.stdout.write(self.style.ERROR(
                "  ✗ credentials rejected — router needs re-onboarding"
            ))
            return
        except ProvisioningError as exc:
            self.stdout.write(self.style.ERROR(f"  ✗ unreachable: {exc}"))
            return

        hits: list[str] = []

        # --- CPU / memory -------------------------------------------------
        cpu = diag.cpu_load
        if cpu is not None:
            mem = diag.mem_used_pct if diag.mem_used_pct is not None else "?"
            line = f"  CPU {cpu}%   mem {mem}%   up {diag.uptime}"
            if cpu >= CPU_WARN:
                self.stdout.write(self.style.ERROR(line + "  ← CPU SATURATED"))
                hits.append(
                    f"Router CPU at {cpu}% — the board is the bottleneck; everything slows "
                    "regardless of per-client limits."
                )
            else:
                self.stdout.write(self.style.SUCCESS(line))
            if diag.mem_used_pct is not None and diag.mem_used_pct >= MEM_WARN:
                hits.append(
                    f"Memory at {diag.mem_used_pct}% — the router is under memory pressure."
                )

        # --- MSS clamp ----------------------------------------------------
        if diag.mss_clamp_present is True:
            self.stdout.write(self.style.SUCCESS("  ✓ TCP-MSS clamp present"))
        elif diag.mss_clamp_present is False:
            self.stdout.write(self.style.ERROR("  ✗ TCP-MSS clamp MISSING"))
            hits.append(
                "The TCP-MSS clamp is missing — PPPoE clients hit a PMTU black hole: HTTPS "
                "and big pages crawl or half-load. Re-provision any client (or re-run "
                "onboarding) to restore it."
            )
        else:
            self.stdout.write(self.style.WARNING("  ! could not read the MSS clamp"))

        # --- oversubscription (sold vs uplink) ----------------------------
        active = Client.objects.filter(router=router, status=Client.Status.ACTIVE)
        active_count = active.count()
        sold_down_mbps = sum(
            (c.plan.download_kbps or 0) for c in active.select_related("plan")
        ) / 1000
        online = diag.pppoe_active_count if diag.pppoe_active_count is not None else "?"
        self.stdout.write(
            f"  clients: {active_count} active in WIFI.OS · {online} dialed in now · "
            f"{sold_down_mbps:.0f} Mbps sold (download)"
        )
        if uplink:
            ratio = sold_down_mbps / uplink if uplink else 0
            msg = (
                f"  oversubscription: {sold_down_mbps:.0f} Mbps sold vs "
                f"{uplink:.0f} Mbps uplink = {ratio:.1f}×"
            )
            if ratio >= 10:
                self.stdout.write(self.style.ERROR(msg + "  ← HIGH"))
                hits.append(
                    f"Oversubscription ~{ratio:.0f}× ({sold_down_mbps:.0f} Mbps sold on a "
                    f"{uplink:.0f} Mbps uplink) — at peak the WAN saturates and every client "
                    "slows. Raise the uplink or add a fair-queue (PCQ) parent queue."
                )
            else:
                self.stdout.write(msg)
        else:
            self.stdout.write("    (pass --uplink <Mbps> for the oversubscription ratio)")

        # --- double-queue sanity -----------------------------------------
        static_count = active.filter(connection_type=Client.Connection.STATIC).count()
        if diag.simple_queue_count is not None:
            note = (
                f"  simple queues on router: {diag.simple_queue_count} "
                f"(static clients expect ~{static_count})"
            )
            if diag.simple_queue_count > static_count + 1:
                self.stdout.write(self.style.WARNING(note + "  ← more than expected"))
                hits.append(
                    f"{diag.simple_queue_count} /queue/simple entries but only {static_count} "
                    "static clients — a PPPoE client may be double-limited by a leftover queue. "
                    "Check /queue/simple for names that aren't 'wifios-…'."
                )
            else:
                self.stdout.write(note)

        # --- live throughput ---------------------------------------------
        if diag.top_interfaces:
            self.stdout.write("  live throughput (busiest interfaces):")
            for i in diag.top_interfaces:
                self.stdout.write(
                    f"    {i.name:<20} ↓{i.rx_mbps:>8.2f} Mbps  ↑{i.tx_mbps:>8.2f} Mbps"
                )

        for n in diag.notes:
            self.stdout.write(self.style.WARNING(f"  ! {n}"))

        # --- verdict ------------------------------------------------------
        self.stdout.write("")
        if hits:
            self.stdout.write(self.style.ERROR("  Likely cause(s):"))
            for h in hits:
                self.stdout.write(self.style.ERROR(f"    • {h}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                "  No obvious router-side cause in this snapshot. If clients still report "
                "slowness, run this AT PEAK (evening) — contention and CPU saturation only "
                "show under load."
            ))
