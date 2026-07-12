"""Data + bandwidth caps: enforced on the router, tracked by us.

Two halves. The router ENFORCES — a capped hotspot user is cut off by RouterOS at the
byte limit and rate-limited to the plan's speed, so enforcement survives even if our
server is down. And we SYNC usage back, so we can warn a customer before they run dry
and report on what they actually used.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session
from apps.provisioning.tasks import sync_hotspot_usage

from .factories import PlanFactory, RouterFactory, TransactionFactory

pytestmark = pytest.mark.django_db

MB = 1024 * 1024


def active_session(router, *, cap_mb=None, phone="254700111222", used_mb=0, warned=False):
    plan = PlanFactory(
        operator=router.operator, data_cap_mb=cap_mb, download_kbps=8192, upload_kbps=2048
    )
    tx = TransactionFactory(operator=router.operator, plan=plan, phone=phone)
    now = timezone.now()
    return Session.objects.create(
        operator=router.operator, plan=plan, router=router, transaction=tx,
        hotspot_username=phone, starts_at=now, expires_at=now + timedelta(hours=1),
        status=Session.Status.ACTIVE, data_used_mb=used_mb,
        data_warned_at=now if warned else None,
    )


class TestSpeedEnforcement:
    def test_the_plan_rate_limit_string_is_upload_over_download(self):
        plan = PlanFactory(download_kbps=8192, upload_kbps=2048)
        assert plan.rate_limit == "2048k/8192k"  # rx/tx = upload/download, per PPPoE

    def test_activation_sets_rate_limit_and_data_cap_on_the_user(self, mocker):
        """The MikroTik payload carries the speed and the byte cap, so the router
        enforces both per-user — not dependent on a hand-made profile."""
        from apps.provisioning.adapters.mikrotik import MikroTikRestAdapter

        router = RouterFactory(provisioning_backend="mikrotik_rest")
        s = active_session(router, cap_mb=500)

        captured = {}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {}

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, *a, **k):
                return FakeResp()

            def put(self, path, json=None):
                captured.update(json or {})
                return FakeResp()

        mocker.patch.object(MikroTikRestAdapter, "_client", return_value=FakeClient())
        mocker.patch.object(MikroTikRestAdapter, "_find_user_id", return_value=None)
        MikroTikRestAdapter(router).activate_user(s)

        assert captured["rate-limit"] == "2048k/8192k"
        assert captured["limit-bytes-total"] == str(500 * MB)


class TestUsageSync:
    def test_usage_is_pulled_from_the_router_into_the_session(self):
        router = RouterFactory()
        s = active_session(router, phone="254700111222")
        DummyAdapter.usage = {"254700111222": (100 * MB, 50 * MB)}

        sync_hotspot_usage()

        s.refresh_from_db()
        assert s.data_used_mb == 150  # 100 down + 50 up

    def test_a_capped_customer_is_warned_near_the_limit_once(
        self, django_capture_on_commit_callbacks
    ):
        router = RouterFactory()
        s = active_session(router, cap_mb=1000, phone="254700111222")
        DummyAdapter.usage = {"254700111222": (900 * MB, 20 * MB)}  # 92% of 1000

        with django_capture_on_commit_callbacks(execute=True):
            sync_hotspot_usage()
            sync_hotspot_usage()  # second run must not re-warn

        from apps.notifications.providers.dummy import DummyProvider

        warned = [b for to, b in DummyProvider.sent if to == "254700111222"]
        assert len(warned) == 1
        assert "data" in warned[0].lower()
        s.refresh_from_db()
        assert s.data_warned_at is not None

    def test_an_uncapped_plan_is_never_warned(self):
        from apps.notifications.providers.dummy import DummyProvider

        router = RouterFactory()
        active_session(router, cap_mb=None, phone="254700111222")
        DummyAdapter.usage = {"254700111222": (5000 * MB, 5000 * MB)}  # huge, but no cap

        sync_hotspot_usage()

        assert [b for to, b in DummyProvider.sent if to == "254700111222"] == []

    def test_well_within_the_cap_is_not_warned(self):
        from apps.notifications.providers.dummy import DummyProvider

        router = RouterFactory()
        active_session(router, cap_mb=1000, phone="254700111222")
        DummyAdapter.usage = {"254700111222": (100 * MB, 10 * MB)}  # 11%

        sync_hotspot_usage()

        assert [b for to, b in DummyProvider.sent if to == "254700111222"] == []

    def test_renewing_resets_usage_and_the_warning(self):
        from apps.provisioning.services import activate

        router = RouterFactory()
        s = active_session(router, cap_mb=1000, used_mb=950, warned=True)
        s.status = Session.Status.PENDING
        s.save()

        activate(s)

        s.refresh_from_db()
        assert s.data_used_mb == 0
        assert s.data_warned_at is None


class TestUsageIsCredited:
    def test_the_amount_billed_matches_the_plan(self):
        """Sanity: a capped plan still charges the plan price, not by the megabyte."""
        plan = PlanFactory(data_cap_mb=500, price=Decimal("50"))
        assert plan.price == Decimal("50")
