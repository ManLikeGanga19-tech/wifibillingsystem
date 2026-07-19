"""Expenses > auto WIFI.OS platform-fees line: what the ISP paid Danamo this month, pulled from
billing (fees + SMS), presented as a positive cost."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import PlatformLedgerEntry
from apps.billing.platform_account import platform_charges

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/ops/platform-fees/"
R = PlatformLedgerEntry.Reason


def staff(operator):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def _entry(operator, amount, reason, *, when=None, period=""):
    e = PlatformLedgerEntry.objects.create(
        operator=operator, amount=Decimal(amount), reason=reason, period=period
    )
    if when is not None:
        PlatformLedgerEntry.objects.filter(pk=e.pk).update(created_at=when)
    return e


class TestPlatformFees:
    def test_sums_this_months_charges_as_a_positive_cost(self):
        op = OperatorFactory()
        _entry(op, "-500", R.BASE_FEE, period="m1")      # charges are stored negative
        _entry(op, "-1900.50", R.COMMISSION)
        _entry(op, "-12", R.SMS)
        # excluded: funding (a top-up), and a fee from a previous month
        _entry(op, "1000", R.TOPUP)
        _entry(op, "-500", R.BASE_FEE, period="m0", when=timezone.now() - timedelta(days=40))

        body = staff(op).get(URL).json()
        assert body["total"] == "2412.50"
        amounts = {line["key"]: line["amount"] for line in body["lines"]}
        assert amounts["base_fee"] == "500.00"
        assert amounts["commission"] == "1900.50"
        assert amounts["sms"] == "12.00"
        assert amounts["pppoe_fee"] == "0.00"  # every fee reason is present, zero if none

    def test_helper_ignores_topups_and_grants(self):
        op = OperatorFactory()
        _entry(op, "1000", R.TOPUP)
        _entry(op, "500", R.GRANT)
        now = timezone.now()
        data = platform_charges(op, start=now - timedelta(days=1), end=now + timedelta(days=1))
        assert data["total"] == Decimal("0.00")

    def test_is_tenant_scoped(self):
        mine, theirs = OperatorFactory(slug="mine"), OperatorFactory(slug="theirs")
        _entry(theirs, "-500", R.BASE_FEE, period="m1")
        assert staff(mine).get(URL).json()["total"] == "0.00"
