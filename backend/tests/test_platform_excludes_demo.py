"""The demo tenant must be invisible to Platform Control's numbers — it exists to be
explored, not to move real money, so counting it would inflate every headline. These pin
that the platform KPIs and overview ignore an is_demo operator entirely."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.core.models import Operator

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db


def _platform():
    c = APIClient()
    c.force_authenticate(user=UserFactory(is_staff=True, role=Role.PLATFORM_OWNER))
    return c


def _sale(operator, amount):
    LedgerEntry.objects.create(
        operator=operator, entry_type=LedgerEntry.Type.SALE, amount=Decimal(amount),
        memo="sale",
    )


def test_kpis_do_not_count_the_demo_tenant():
    c = _platform()
    before = c.get("/api/v1/platform/kpis/").json()["tenants_total"]

    OperatorFactory(slug="demo-x", is_demo=True, status=Operator.Status.ACTIVE)
    after_demo = c.get("/api/v1/platform/kpis/").json()["tenants_total"]
    assert after_demo == before  # the demo did not change the count

    OperatorFactory(slug="real-x", is_demo=False, status=Operator.Status.ACTIVE)
    after_real = c.get("/api/v1/platform/kpis/").json()["tenants_total"]
    assert after_real == before + 1  # a real ISP does


def test_gross_volume_ignores_demo_sales():
    c = _platform()
    demo = OperatorFactory(slug="demo-y", is_demo=True, status=Operator.Status.ACTIVE)
    real = OperatorFactory(slug="real-y", is_demo=False, status=Operator.Status.ACTIVE)

    _sale(demo, "9999")   # must NOT show up
    _sale(real, "1000")   # must show up

    body = c.get("/api/v1/platform/kpis/").json()
    assert Decimal(str(body["gross_volume_month"])) == Decimal("1000")


def test_overview_also_excludes_demo():
    c = _platform()
    before = c.get("/api/v1/platform/overview/").json()["tenants_total"]
    OperatorFactory(slug="demo-z", is_demo=True, status=Operator.Status.ACTIVE)
    after = c.get("/api/v1/platform/overview/").json()["tenants_total"]
    assert after == before
