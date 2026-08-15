"""Seed the read-only DEMO tenant — a fully-populated WIFI.OS showcase.

The point: someone can log in and see every screen alive (dashboard, hotspot, PPPoE,
billing, churn, active users, ops) without a single real customer, and — because the tenant
is is_demo — the API refuses every write, so nothing they click can change the data.

Idempotent: it wipes the demo tenant's own rows and rebuilds them from a fixed random seed,
so each run yields the same believable snapshot. It only ever touches the demo operator.
"""

import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

DEMO_SLUG = "demo"
DEMO_OWNER_PHONE = "254799000000"
DEMO_OWNER_PASSWORD = "demo1234"

FIRST_NAMES = [
    "Amina", "Brian", "Cynthia", "David", "Esther", "Felix", "Grace", "Hassan", "Irene",
    "James", "Keziah", "Lewis", "Mercy", "Nashon", "Otieno", "Purity", "Quresha", "Ruth",
    "Samuel", "Teresa", "Umi", "Victor", "Wanjiru", "Xavier", "Yusuf", "Zawadi",
]
LAST_NAMES = [
    "Achieng", "Barasa", "Chege", "Daudi", "Ekiru", "Gitau", "Hamisi", "Juma", "Kamau",
    "Kiptoo", "Mwangi", "Njoroge", "Omondi", "Wafula", "Wekesa",
]
LOCATIONS = ["Kibera", "Rongai", "Kasarani", "Umoja", "Githurai", "Kikuyu", "Ruaka", "Buruburu"]

HOTSPOT_PLANS = [
    # name, price, duration, down_kbps, up_kbps, shared, cap_mb
    ("1 Hour Express", 20, timedelta(hours=1), 5120, 2048, 1, None),
    ("3 Hours Standard", 50, timedelta(hours=3), 3072, 1024, 1, None),
    ("Daily Unlimited", 100, timedelta(days=1), 5120, 2048, 1, None),
    ("Weekly Premium", 350, timedelta(days=7), 6144, 3072, 2, None),
    ("Monthly Home", 2000, timedelta(days=30), 10240, 5120, 3, 51200),
]
PPPOE_PLANS = [
    # name, price, down_kbps, up_kbps, cap_gb, sort
    ("Bronze 8 Mbps", 2000, 8192, 4096, None, 1),
    ("Silver 10 Mbps", 2500, 10240, 5120, None, 2),
    ("Gold 15 Mbps", 3500, 15360, 7680, None, 3),
    ("Platinum 30 Mbps", 6000, 30720, 15360, None, 4),
]


class Command(BaseCommand):
    help = "Seed the read-only demo tenant (idempotent)."

    def handle(self, *args, **options):
        self.rng = random.Random(42)
        op = self._operator()
        self._wipe(op)
        self._owner(op)
        plans = self._hotspot_plans(op)
        service_plans = self._pppoe_plans(op)
        routers = self._routers(op)
        towers, aps = self._topology(op, routers)
        subs = self._subscribers(op)
        self._transactions(op, subs, plans, routers)
        self._sessions(op, subs, plans, routers)
        self._vouchers(op, plans)
        self._pppoe_clients(op, service_plans, routers, aps)
        self._wallet(op)
        self._ops(op, subs, routers)
        self._platform_showcase()
        self._onboarding_showcase()
        self._offboarding_showcase()
        self._broadcast_showcase()
        self.stdout.write(self.style.SUCCESS(
            f"Demo tenant ready: https://{DEMO_SLUG}.wifios.co.ke  "
            f"login {DEMO_OWNER_PHONE} / {DEMO_OWNER_PASSWORD} (READ-ONLY)"
        ))

    # -- foundations --------------------------------------------------------------

    def _operator(self):
        from apps.core.models import Operator

        op, _ = Operator.objects.get_or_create(
            slug=DEMO_SLUG,
            defaults={"name": "WIFI.OS Demo ISP"},
        )
        # A normal, live, trading ISP — so the go-live gate is satisfied and every money
        # screen shows real figures — just flagged is_demo so writes are refused.
        op.name = "WIFI.OS Demo ISP"
        op.status = Operator.Status.ACTIVE
        op.is_active = True
        op.is_demo = True
        op.is_platform_owned = False
        op.settlement_method = Operator.Settlement.PAYBILL
        op.settlement_paybill = "4123456"
        op.settlement_paybill_account = "DEMO"
        op.settlement_name = "WIFI.OS Demo"
        op.settlement_verified_at = timezone.now()
        op.owner_name = "Demo Owner"
        op.save()
        self.stdout.write(f"Operator: {op.name} [demo, read-only]")
        return op

    def _wipe(self, op):
        """Delete only the demo tenant's rows, child-first (respecting PROTECT), so a re-run
        rebuilds a clean, identical snapshot without ever touching another ISP."""
        from apps.accounts.models import Subscriber
        from apps.billing.models import LedgerEntry
        from apps.ops.models import Equipment, Lead, Ticket
        from apps.payments.models import Transaction
        from apps.plans.models import Plan
        from apps.pppoe.models import (
            AccessPoint,
            Client,
            ClientLifecycleEvent,
            Invoice,
            ServicePlan,
            Tower,
        )
        from apps.provisioning.models import Router, Session
        from apps.vouchers.models import Voucher

        # Sessions FIRST: deleting a Transaction/Voucher SET_NULLs session.transaction/voucher,
        # which would violate the "a session must have a payment source" constraint. Kill the
        # sessions before the things they point at.
        for model in (
            LedgerEntry, Session, Transaction, Voucher, Invoice, ClientLifecycleEvent,
            Client, AccessPoint, Tower, ServicePlan, Plan, Equipment, Router, Ticket,
            Lead, Subscriber,
        ):
            model.objects.filter(operator=op).delete()

    def _owner(self, op):
        from apps.accounts.models import Role, User

        user = User.objects.filter(phone=DEMO_OWNER_PHONE).first()
        if user is None:
            user = User.objects.create_user(
                phone=DEMO_OWNER_PHONE,
                password=DEMO_OWNER_PASSWORD,
                name="Demo ISP Owner",
                operator=op,
                role=Role.TENANT_OWNER,
                is_staff=True,
            )
        else:
            user.operator = op
            user.role = Role.TENANT_OWNER
            user.is_staff = True
            user.set_password(DEMO_OWNER_PASSWORD)
            user.save()
        return user

    # -- catalogue ----------------------------------------------------------------

    def _hotspot_plans(self, op):
        from apps.plans.models import Plan

        plans = []
        for name, price, dur, down, up, shared, cap in HOTSPOT_PLANS:
            plans.append(Plan.objects.create(
                operator=op, name=name, price=price, duration=dur,
                download_kbps=down, upload_kbps=up, shared_users=shared, data_cap_mb=cap,
            ))
        return plans

    def _pppoe_plans(self, op):
        from apps.pppoe.models import ServicePlan

        plans = []
        for name, price, down, up, cap, sort in PPPOE_PLANS:
            plans.append(ServicePlan.objects.create(
                operator=op, name=name, price=Decimal(price), download_kbps=down,
                upload_kbps=up, data_cap_gb=cap, sort_order=sort,
                mikrotik_profile=name.lower().split()[0],
            ))
        return plans

    def _routers(self, op):
        from apps.provisioning.models import Router

        routers = []
        for i, name in enumerate(("Kibera Site A", "Rongai Site B"), start=1):
            routers.append(Router.objects.create(
                operator=op, name=name, management_host=f"10.88.0.{i}",
                provisioning_backend=Router.Backend.DUMMY,
                status=Router.Status.ONLINE, last_seen_at=timezone.now(),
            ))
        return routers

    def _topology(self, op, routers):
        from apps.pppoe.models import AccessPoint, Tower

        towers, aps = [], []
        for i, rt in enumerate(routers):
            tower = Tower.objects.create(
                operator=op, name=f"{rt.name.split()[0]} Tower",
                gps_lat=Decimal("-1.30") - Decimal(i) / 100, gps_lng=Decimal("36.80"),
            )
            towers.append(tower)
            for mode in (AccessPoint.Mode.PTMP, AccessPoint.Mode.AP):
                aps.append(AccessPoint.objects.create(
                    operator=op, tower=tower, name=f"{tower.name} {mode}", mode=mode,
                    capacity=30, band="5GHz", router=rt,
                ))
        return towers, aps

    def _name(self):
        return f"{self.rng.choice(FIRST_NAMES)} {self.rng.choice(LAST_NAMES)}"

    def _phone(self):
        return "2547" + "".join(str(self.rng.randint(0, 9)) for _ in range(8))

    def _subscribers(self, op):
        from apps.accounts.models import Subscriber

        subs = []
        for _ in range(30):
            subs.append(Subscriber.objects.create(
                operator=op, phone=self._phone(), name=self._name(),
            ))
        return subs

    # -- hotspot activity ---------------------------------------------------------

    def _transactions(self, op, subs, plans, routers):
        from apps.payments.models import Transaction

        now = timezone.now()
        for _ in range(120):
            when = now - timedelta(days=self.rng.randint(0, 29),
                                   hours=self.rng.randint(0, 23))
            sub = self.rng.choice(subs)
            plan = self.rng.choice(plans)
            roll = self.rng.random()
            if roll < 0.82:
                status, cb = Transaction.Status.SUCCESS, when
            elif roll < 0.92:
                status, cb = Transaction.Status.FAILED, when
            else:
                status, cb = Transaction.Status.PENDING, None
            Transaction.objects.create(
                operator=op, subscriber=sub, plan=plan, router=self.rng.choice(routers),
                phone=sub.phone, amount=plan.price, status=status,
                callback_received_at=cb, created_at=when,
                checkout_request_id=f"ws_CO_{uuid.uuid4().hex[:16]}",
                mpesa_receipt=("Q" + uuid.uuid4().hex[:9].upper()
                               if status == Transaction.Status.SUCCESS else ""),
                account_reference="HOTSPOT",
            )

    def _sessions(self, op, subs, plans, routers):
        from apps.payments.models import Transaction
        from apps.provisioning.models import Session

        now = timezone.now()
        for i in range(28):
            sub = self.rng.choice(subs)
            plan = self.rng.choice(plans)
            router = self.rng.choice(routers)
            active = i < 16  # a healthy live count
            starts = now - timedelta(hours=self.rng.randint(0, 20))
            # A session must carry a payment source (DB constraint) — the paid transaction
            # that bought it, exactly like the real flow.
            tx = Transaction.objects.create(
                operator=op, subscriber=sub, plan=plan, router=router, phone=sub.phone,
                amount=plan.price, status=Transaction.Status.SUCCESS,
                callback_received_at=starts, created_at=starts,
                checkout_request_id=f"ws_CO_{uuid.uuid4().hex[:16]}",
                mpesa_receipt="Q" + uuid.uuid4().hex[:9].upper(), account_reference="HOTSPOT",
            )
            Session.objects.create(
                operator=op, subscriber=sub, plan=plan, router=router, transaction=tx,
                hotspot_username=sub.phone, hotspot_password="demo",
                starts_at=starts, expires_at=starts + plan.duration,
                status=Session.Status.ACTIVE if active else Session.Status.EXPIRED,
                mac_address=":".join(f"{self.rng.randint(0, 255):02X}" for _ in range(6)),
                ip_address=f"10.5.50.{self.rng.randint(10, 250)}",
            )

    def _vouchers(self, op, plans):
        from apps.vouchers.models import Voucher

        for i in range(24):
            redeemed = i < 9
            Voucher.objects.create(
                operator=op, plan=self.rng.choice(plans),
                code="WIFI" + "".join(
                    self.rng.choice("ACDEFHJKMNPRTWXY34679") for _ in range(6)),
                status=Voucher.Status.REDEEMED if redeemed else Voucher.Status.UNUSED,
                redeemed_at=timezone.now() - timedelta(days=self.rng.randint(0, 20))
                if redeemed else None,
            )

    # -- broadband (PPPoE) --------------------------------------------------------

    def _pppoe_clients(self, op, service_plans, routers, aps):
        from apps.pppoe.models import (
            Client,
            ClientLifecycleEvent,
            Invoice,
            PppoeSettings,
        )

        PppoeSettings.objects.update_or_create(
            operator=op,
            defaults={"churn_after_suspended_days": 60, "auto_generate_invoices": True,
                      "pre_expiry_reminder_hours": [24, 72]},
        )

        today = timezone.localdate()
        now = timezone.now()
        # A believable base: mostly active (many online), a handful suspended, a couple
        # churned, a couple pending install — so every status filter and the churn/KPI
        # tiles have something real to show.
        statuses = (
            [Client.Status.ACTIVE] * 22
            + [Client.Status.SUSPENDED] * 4
            + [Client.Status.CANCELLED] * 3
            + [Client.Status.PENDING_INSTALL] * 2
        )
        E = ClientLifecycleEvent.Event
        for i, status in enumerate(statuses):
            plan = self.rng.choice(service_plans)
            name = self._name()
            activated_at = now - timedelta(days=self.rng.randint(20, 150))
            billing_day = self.rng.randint(1, 28)
            online = status == Client.Status.ACTIVE and self.rng.random() < 0.7
            # Roughly a quarter of the base is static-IP (no login, enforced by queue + IP) so
            # the demo shows both connection types side by side.
            is_static = i % 4 == 0
            static_ip = f"10.20.{i}.{self.rng.randint(2, 250)}" if is_static else None
            client = Client.objects.create(
                operator=op, account_number=f"DEMO{i + 1:05d}", full_name=name,
                phone=self._phone(), plan=plan, router=self.rng.choice(routers),
                access_point=self.rng.choice(aps),
                connection_type=(
                    Client.Connection.STATIC if is_static else Client.Connection.PPPOE
                ),
                static_ip=static_ip,
                pppoe_username=None if is_static else f"demo-{i + 1:03d}",
                pppoe_password="" if is_static else uuid.uuid4().hex[:10],
                status=status, billing_day=billing_day,
                next_due_date=today + timedelta(days=self.rng.randint(-5, 20)),
                installed_at=activated_at.date(),
                status_changed_at=activated_at,
                is_online=online,
                last_online_at=now - timedelta(minutes=self.rng.randint(1, 240)),
                wan_ip=static_ip if is_static else (
                    f"41.90.{self.rng.randint(1, 254)}.{self.rng.randint(1, 254)}"
                ),
                session_uptime=f"{self.rng.randint(1, 20)}d{self.rng.randint(0, 23)}h",
            )
            # Lifecycle trail so churn analytics + the PPPoE KPI tiles read real trends.
            self._events_for(client, status, activated_at, E)
            # A few months of invoices, some paid, latest possibly open.
            self._invoices_for(client, plan, today, Invoice)

    def _events_for(self, client, status, activated_at, E):
        from apps.pppoe.models import Client, ClientLifecycleEvent

        def ev(kind, when, to):
            ClientLifecycleEvent.objects.create(
                operator=client.operator, client=client,
                account_number=client.account_number, full_name=client.full_name,
                event=kind, to_status=to, occurred_at=when,
            )

        ev(E.ACTIVATED, activated_at, Client.Status.ACTIVE)
        if status == Client.Status.SUSPENDED:
            ev(E.SUSPENDED, client.status_changed_at, Client.Status.SUSPENDED)
        elif status == Client.Status.CANCELLED:
            susp = activated_at + timedelta(days=self.rng.randint(20, 60))
            ev(E.SUSPENDED, susp, Client.Status.SUSPENDED)
            ev(E.CANCELLED, susp + timedelta(days=self.rng.randint(30, 80)),
               Client.Status.CANCELLED)

    def _invoices_for(self, client, plan, today, Invoice):
        for m in range(3):
            period = (today.replace(day=1) - timedelta(days=31 * m)).replace(day=1)
            paid = m > 0 or self.rng.random() < 0.6
            Invoice.objects.create(
                operator=client.operator, client=client,
                number=f"INV-{client.account_number}-{m}"[:24],
                period_start=period, period_end=period + timedelta(days=27),
                amount=plan.price, due_date=period + timedelta(days=5),
                status=Invoice.Status.PAID if paid else Invoice.Status.UNPAID,
                paid_at=timezone.now() - timedelta(days=self.rng.randint(1, 20))
                if paid else None,
            )

    # -- money & ops --------------------------------------------------------------

    def _wallet(self, op):
        from apps.billing.models import LedgerEntry

        now = timezone.now()
        for d in range(30, 0, -1):
            LedgerEntry.objects.create(
                operator=op, entry_type=LedgerEntry.Type.SALE,
                amount=Decimal(self.rng.randint(800, 6000)),
                memo="Daily settled sales", created_at=now - timedelta(days=d),
            )

    def _ops(self, op, subs, routers):
        from apps.ops.models import Equipment, Lead, Ticket

        subjects = [
            ("Slow speeds in the evening", Ticket.Priority.NORMAL, Ticket.Status.OPEN),
            ("No connection since morning", Ticket.Priority.HIGH, Ticket.Status.IN_PROGRESS),
            ("Requesting plan upgrade", Ticket.Priority.LOW, Ticket.Status.RESOLVED),
            ("Router keeps rebooting", Ticket.Priority.URGENT, Ticket.Status.OPEN),
            ("Billing question", Ticket.Priority.NORMAL, Ticket.Status.RESOLVED),
        ]
        for subject, prio, st in subjects:
            Ticket.objects.create(
                operator=op, subject=subject, subscriber=self.rng.choice(subs),
                priority=prio, status=st,
                resolved_at=timezone.now() if st == Ticket.Status.RESOLVED else None,
            )

        for _ in range(6):
            Lead.objects.create(
                operator=op, name=self._name(), phone=self._phone(),
                location=self.rng.choice(LOCATIONS),
                status=self.rng.choice([Lead.Status.NEW, Lead.Status.CONTACTED,
                                        Lead.Status.CONVERTED]),
            )

        gear = [
            ("MikroTik RB5009", Equipment.Type.ROUTER, Equipment.Status.DEPLOYED),
            ("Ubiquiti LiteBeam 5AC", Equipment.Type.ANTENNA, Equipment.Status.DEPLOYED),
            ("TP-Link 24-port Switch", Equipment.Type.SWITCH, Equipment.Status.IN_STORE),
            ("Reyee CPE RG-EW", Equipment.Type.CPE, Equipment.Status.IN_STORE),
        ]
        for name, kind, st in gear:
            Equipment.objects.create(
                operator=op, name=name, equipment_type=kind, status=st,
                router=self.rng.choice(routers) if st == Equipment.Status.DEPLOYED else None,
                serial_number=uuid.uuid4().hex[:10].upper(),
                cost=Decimal(self.rng.randint(3000, 45000)),
            )

    # -- platform showcase (Growth / KPIs / P&L) ----------------------------------

    #: A handful of sample ISP tenants with 6 months of platform-fee history, so Platform
    #: Control's Growth waterfall, MRR and P&L render REAL numbers. These are NON-demo on
    #: purpose — the demo tenant is excluded from platform figures, so it can't populate them.
    #: base_fee + a monthly pppoe-fee series (oldest→newest); 0 = not paying that month, which
    #: drives the New / Churned buckets. A healthy growth story with a bit of churn.
    SHOWCASE_ISPS = [
        ("Kilifi Connect", "isp-kilifi", [4000, 4500, 5000, 5500, 6000, 6500]),   # expansion
        ("Nyali Networks", "isp-nyali", [2000, 2500, 3000, 3500, 4000, 4500]),     # expansion
        ("Bamburi WiFi", "isp-bamburi", [3000, 3200, 3400, 3600, 3800, 4000]),     # expansion
        ("Mtwapa Mesh", "isp-mtwapa", [1500, 1700, 1900, 2100, 2300, 2500]),       # expansion
        ("Diani Broadband", "isp-diani", [0, 0, 0, 0, 0, 5000]),                   # NEW this month
        ("Likoni Links", "isp-likoni", [2000, 2100, 2200, 2300, 2400, 0]),         # CHURNED
        ("Malindi Fibre", "isp-malindi", [6000, 6200, 6400, 6600, 6800, 5500]),    # CONTRACTION
    ]
    BASE_FEE = 500

    def _platform_showcase(self):
        from apps.billing.models import PlatformLedgerEntry
        from apps.core.models import Operator, TenantLifecycleEvent

        now = timezone.now()
        # 6 month anchors, oldest → newest, mid-month so timezone can't shift the bucket.
        # The newest anchor is capped just below `now`: precise churn compares against the
        # live instant, so an event dated later this month (day 15 when today is the 14th)
        # would fall in the future and be missed.
        months = []
        d = now
        for _ in range(6):
            anchor = d.replace(day=15, hour=12, minute=0, second=0, microsecond=0)
            if anchor >= now:
                anchor = now - timedelta(hours=1)
            months.append(anchor)
            d = d.replace(day=1) - timedelta(days=5)
        months.reverse()

        for name, slug, pppoe_series in self.SHOWCASE_ISPS:
            op, _ = Operator.objects.get_or_create(slug=slug, defaults={"name": name})
            op.name = name
            # Current status reflects the LAST month: still paying → active, dropped → suspended.
            op.status = (Operator.Status.ACTIVE if pppoe_series[-1] > 0
                         else Operator.Status.SUSPENDED)
            op.is_active = True
            op.is_demo = False
            # Onboarded when they first went live — so the onboarding funnel sees them as
            # fully activated back then (and mostly OUTSIDE its 90-day window), not as
            # brand-new signups stuck at stage one.
            first_live = next((m for m, p in zip(months, pppoe_series, strict=True) if p > 0),
                              months[0])
            op.approved_at = first_live
            op.settlement_verified_at = first_live + timedelta(days=1)
            op.save()
            Operator.objects.filter(pk=op.pk).update(created_at=first_live - timedelta(days=2))
            PlatformLedgerEntry.objects.filter(operator=op, memo="showcase").delete()
            TenantLifecycleEvent.objects.filter(operator=op, reason="showcase").delete()
            was_live = False
            ever_activated = False
            for when, pppoe in zip(months, pppoe_series, strict=True):
                # Emit a lifecycle event on every live-ness flip, so precise (status-based)
                # tenant churn has real transitions to count — Diani activates late, Likoni
                # churns in the last month.
                now_live = pppoe > 0
                if now_live and not was_live:
                    ev = (TenantLifecycleEvent.Event.REACTIVATED if ever_activated
                          else TenantLifecycleEvent.Event.ACTIVATED)
                    self._plat_event(op, ev, "active", when)
                    ever_activated = True
                elif was_live and not now_live:
                    self._plat_event(op, TenantLifecycleEvent.Event.SUSPENDED, "suspended", when)
                was_live = now_live
                if pppoe == 0:  # not paying this month → nothing accrues
                    continue
                period = when.strftime("%Y-%m")
                base = PlatformLedgerEntry.Reason.BASE_FEE
                fee = PlatformLedgerEntry.Reason.PPPOE_FEE
                # Fees are stored NEGATIVE (they debit the ISP); MRR negates them back.
                self._plat_fee(op, base, -self.BASE_FEE, period, when)
                self._plat_fee(op, fee, -pppoe, period, when)
        self.stdout.write(f"Platform showcase: {len(self.SHOWCASE_ISPS)} sample ISPs w/ 6mo fees")

    def _broadcast_showcase(self):
        """One live platform broadcast, so every ISP console shows the notice banner."""
        from apps.core.models import PlatformBroadcast

        PlatformBroadcast.objects.filter(body__startswith="[seed]").delete()  # idempotent
        PlatformBroadcast.objects.create(
            title="Scheduled maintenance — Sunday 02:00–04:00 EAT",
            body="[seed] We'll be upgrading the payments pipeline. Collections keep working; "
                 "the console may be briefly read-only during the window.",
            level=PlatformBroadcast.Level.WARNING,
        )
        self.stdout.write("Broadcast showcase: 1 live notice")

    def _offboarding_showcase(self):
        """Put one recent signup into a live grace window, so Platform Control shows the
        offboarding banner (undo / complete) and a tenant frozen mid-departure."""
        from apps.core.models import Operator, TenantOffboarding
        from apps.core.offboarding import initiate_offboarding

        op = Operator.objects.filter(slug="signup-ganze").first()
        if not op:
            return
        # Idempotent on reseed: clear any prior offboarding and return the tenant to a clean
        # active state before starting a fresh one.
        TenantOffboarding.objects.filter(operator=op).delete()
        op.status = Operator.Status.ACTIVE
        op.is_active = True
        op.suspension_reason = ""
        op.save(update_fields=["status", "is_active", "suspension_reason", "updated_at"])
        initiate_offboarding(
            op, reason="Migrating to a competitor — winding down", actor=None, grace_days=10
        )
        self.stdout.write("Offboarding showcase: 1 tenant in a grace window")

    def _plat_event(self, op, event, to_status, when):
        from apps.core.models import TenantLifecycleEvent

        TenantLifecycleEvent.objects.create(
            operator=op, slug=op.slug, name=op.name, event=event,
            to_status=to_status, reason="showcase", occurred_at=when,
        )

    def _plat_fee(self, op, reason, amount, period, when):
        from apps.billing.models import PlatformLedgerEntry

        e = PlatformLedgerEntry.objects.create(
            operator=op, reason=reason, amount=Decimal(amount), period=period, memo="showcase",
        )
        # created_at is auto_now_add; MRR movement buckets by it, so backdate to the month.
        PlatformLedgerEntry.objects.filter(pk=e.pk).update(created_at=when)

    # -- onboarding funnel showcase ----------------------------------------------------------

    #: Recent ISP signups at every stage of the onboarding funnel, so Platform Growth's
    #: funnel (a 90-day cohort) shows real drop-off instead of an empty chart. The 6-month
    #: MRR-showcase ISPs above are too OLD to fall in that window, so this is a separate set.
    #: (name, slug, days_ago, stage) — stage ladder: signed < activated < verified < paid.
    RECENT_SIGNUPS = [
        ("Watamu Wireless", "signup-watamu", 3, "verified"),
        ("Kilifi Coast Net", "signup-kcoast", 8, "paid"),
        ("Shanzu Fibre", "signup-shanzu", 12, "signed"),       # stuck: pending > 7 days
        ("Vipingo Links", "signup-vipingo", 18, "activated"),  # stuck: live 14d+, no payment
        ("Mariakani Mesh", "signup-mariakani", 25, "paid"),
        ("Rabai Radio", "signup-rabai", 40, "verified"),
        ("Kaloleni Connect", "signup-kaloleni", 55, "paid"),
        ("Ganze Gateway", "signup-ganze", 70, "activated"),    # stuck: live 14d+, no payment
    ]
    _LADDER = ["signed", "activated", "verified", "paid"]

    def _onboarding_showcase(self):
        from apps.core.models import Operator, TenantLifecycleEvent
        from apps.payments.models import C2BPayment

        now = timezone.now()
        for name, slug, days_ago, stage in self.RECENT_SIGNUPS:
            reached = self._LADDER.index(stage)
            created = now - timedelta(days=days_ago)
            approved = created + timedelta(days=2) if reached >= 1 else None
            op, _ = Operator.objects.get_or_create(slug=slug, defaults={"name": name})
            op.name = name
            op.is_demo = False
            op.is_platform_owned = False
            op.status = (Operator.Status.ACTIVE if reached >= 1 else Operator.Status.PENDING)
            op.approved_at = approved
            op.settlement_verified_at = (approved + timedelta(days=1)) if reached >= 2 else None
            op.save()
            Operator.objects.filter(pk=op.pk).update(created_at=created)  # bypass auto_now_add

            TenantLifecycleEvent.objects.filter(operator=op, reason="showcase").delete()
            if approved:
                self._plat_event(op, TenantLifecycleEvent.Event.ACTIVATED, "active", approved)

            # "First payment" = one matched C2B collection. Lightweight: no plan/subscriber.
            C2BPayment.objects.filter(operator=op, raw_payload={"seed": "onboarding"}).delete()
            if reached >= 3:
                p = C2BPayment.objects.create(
                    operator=op, trans_id=f"SEED{uuid.uuid4().hex[:8].upper()}",
                    bill_ref=slug, amount=Decimal("500"),
                    status=C2BPayment.Status.MATCHED, raw_payload={"seed": "onboarding"},
                )
                C2BPayment.objects.filter(pk=p.pk).update(
                    received_at=approved + timedelta(days=3))
        self.stdout.write(f"Onboarding showcase: {len(self.RECENT_SIGNUPS)} recent signups")
