"""Slow-speed diagnostics: the read-only diagnose action, the oversubscription math, health
trending on the health-check cadence, the MSS-clamp self-heal, and sample pruning."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.provisioning.adapters.base import DeviceInfo
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import RouterHealthSample
from apps.provisioning.tasks import (
    _record_health_sample,
    heal_pppoe_mss_clamps,
    prune_router_health_samples,
)

from .factories import PppoeClientFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db


def staff(operator):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


class TestDiagnoseAction:
    def test_reports_oversubscription_against_uplink(self):
        router = RouterFactory(uplink_mbps=100)
        # Three active clients at 10 Mbps down each = 30 Mbps sold on a 100 Mbps uplink.
        PppoeClientFactory.create_batch(
            3, operator=router.operator, router=router,
            plan__operator=router.operator, plan__download_kbps=10240, status="active",
        )
        resp = staff(router.operator).get(f"/api/v1/routers/{router.id}/diagnose/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_clients"] == 3
        assert body["sold_download_mbps"] == 30.7  # 10240 kbps ÷ 1000 × 3
        assert body["uplink_mbps"] == 100
        assert body["oversubscription_ratio"] == 0.3
        # Dummy router reports a healthy clamp.
        assert body["mss_clamp_present"] is True

    def test_ratio_is_null_without_uplink(self):
        router = RouterFactory(uplink_mbps=None)
        resp = staff(router.operator).get(f"/api/v1/routers/{router.id}/diagnose/")
        assert resp.status_code == 200
        assert resp.json()["oversubscription_ratio"] is None

    def test_is_tenant_scoped(self):
        mine = RouterFactory(operator__slug="isp-a")
        theirs = RouterFactory(operator__slug="isp-b")
        resp = staff(mine.operator).get(f"/api/v1/routers/{theirs.id}/diagnose/")
        assert resp.status_code == 404  # another ISP's router is invisible


class TestHealthTrending:
    def _info(self, cpu, free=50, total=100, users=2):
        return DeviceInfo(cpu_load=cpu, free_memory=free, total_memory=total, active_users=users)

    def test_records_a_sample(self):
        router = RouterFactory()
        _record_health_sample(router, self._info(cpu=42, free=40, total=100))
        sample = RouterHealthSample.objects.get(router=router)
        assert sample.cpu_load == 42
        assert sample.mem_used_pct == 60  # 100 - 40% free
        assert sample.operator_id == router.operator_id

    def test_throttles_within_the_interval(self):
        router = RouterFactory()
        _record_health_sample(router, self._info(cpu=10))
        _record_health_sample(router, self._info(cpu=99))  # too soon — dropped
        assert RouterHealthSample.objects.filter(router=router).count() == 1

    def test_skips_when_no_device_info(self):
        router = RouterFactory()
        _record_health_sample(router, None)
        _record_health_sample(router, self._info(cpu=None))
        assert RouterHealthSample.objects.filter(router=router).count() == 0

    def test_trend_endpoint_returns_peak(self):
        router = RouterFactory()
        RouterHealthSample.objects.create(operator=router.operator, router=router, cpu_load=30)
        RouterHealthSample.objects.create(operator=router.operator, router=router, cpu_load=95)
        resp = staff(router.operator).get(f"/api/v1/routers/{router.id}/health-trend/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["peak_cpu_24h"] == 95
        assert len(body["samples"]) == 2


class TestMssClampHeal:
    def test_reasserts_clamp_on_routers_with_pppoe(self):
        client = PppoeClientFactory(status="active")
        DummyAdapter.calls = []
        assert heal_pppoe_mss_clamps() == 1
        assert ("mss_clamp", client.router.pk) in DummyAdapter.calls

    def test_skips_routers_without_pppoe_clients(self):
        RouterFactory()  # a router with no clients
        DummyAdapter.calls = []
        assert heal_pppoe_mss_clamps() == 0

    def test_heal_action_restores_clamp_now(self):
        router = RouterFactory()
        DummyAdapter.calls = []
        resp = staff(router.operator).post(f"/api/v1/routers/{router.id}/heal-mss-clamp/")
        assert resp.status_code == 200
        assert ("mss_clamp", router.pk) in DummyAdapter.calls


class TestSamplePruning:
    def test_prunes_old_samples_only(self):
        router = RouterFactory()
        fresh = RouterHealthSample.objects.create(
            operator=router.operator, router=router, cpu_load=10
        )
        old = RouterHealthSample.objects.create(
            operator=router.operator, router=router, cpu_load=20
        )
        # Backdate one past the 14-day window (auto_now_add means we update after create).
        RouterHealthSample.objects.filter(pk=old.pk).update(
            sampled_at=timezone.now() - timedelta(days=20)
        )
        assert prune_router_health_samples() == 1
        assert RouterHealthSample.objects.filter(pk=fresh.pk).exists()
        assert not RouterHealthSample.objects.filter(pk=old.pk).exists()
