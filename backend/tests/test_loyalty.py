"""Loyalty points (Phase 1: earn + config + balances).

Points are money, so the tests guard the money-shaped properties: earn is proportional to
spend, credited EXACTLY ONCE per payment (a replayed callback can't double-credit), never when
the programme is off, and one ISP's points are theirs alone.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.loyalty.models import LoyaltyAccount, LoyaltyLedgerEntry, LoyaltySettings
from apps.loyalty.services import award_for_transaction, settings_for
from apps.notifications.models import Message

from .factories import OperatorFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db

SETTINGS = "/api/v1/loyalty/settings/"
SUMMARY = "/api/v1/loyalty/summary/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def _enable(operator, **kw):
    row = settings_for(operator)
    row.is_enabled = True
    for k, v in kw.items():
        setattr(row, k, v)
    row.save()
    return row


# --- earning ----------------------------------------------------------------------------


class TestEarn:
    def test_points_are_proportional_to_spend(self):
        cfg = LoyaltySettings(spend_per_point=100, points_per_threshold=1)
        assert cfg.points_for(250) == 2  # two whole KES-100 thresholds crossed
        assert cfg.points_for(2000) == 20
        assert cfg.points_for(50) == 0

    def test_a_payment_earns_points_when_the_programme_is_on(self):
        op = OperatorFactory()
        _enable(op, spend_per_point=100, points_per_threshold=1)
        tx = TransactionFactory(operator=op, amount=250, phone="254700111222")
        assert award_for_transaction(tx) is True
        acct = LoyaltyAccount.objects.get(operator=op, phone="254700111222")
        assert acct.points_balance == 2

    def test_earning_is_idempotent_per_transaction(self):
        op = OperatorFactory()
        _enable(op, spend_per_point=100, points_per_threshold=1)
        tx = TransactionFactory(operator=op, amount=500, phone="254700111333")
        assert award_for_transaction(tx) is True
        assert award_for_transaction(tx) is False  # replayed callback -> no second credit
        acct = LoyaltyAccount.objects.get(operator=op, phone="254700111333")
        assert acct.points_balance == 5
        assert LoyaltyLedgerEntry.objects.filter(account=acct, kind="earn").count() == 1

    def test_nothing_earned_when_the_programme_is_off(self):
        op = OperatorFactory()  # default: disabled
        tx = TransactionFactory(operator=op, amount=500, phone="254700111444")
        assert award_for_transaction(tx) is False
        assert not LoyaltyAccount.objects.filter(operator=op).exists()

    def test_a_small_payment_below_the_threshold_earns_nothing(self):
        op = OperatorFactory()
        _enable(op, spend_per_point=100, points_per_threshold=1)
        tx = TransactionFactory(operator=op, amount=50, phone="254700111555")
        assert award_for_transaction(tx) is False

    def test_earning_notifies_when_the_template_is_on(self):
        op = OperatorFactory()
        _enable(op, spend_per_point=100, points_per_threshold=1)
        award_for_transaction(TransactionFactory(operator=op, amount=300, phone="254700111666"))
        msg = Message.objects.filter(operator=op, to_phone="254700111666").first()
        assert msg is not None and "3" in msg.body  # earned 3 points

    def test_points_are_tenant_isolated(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        _enable(a, spend_per_point=100, points_per_threshold=1)
        award_for_transaction(TransactionFactory(operator=a, amount=500, phone="254700999000"))
        # B has no account for that phone.
        assert not LoyaltyAccount.objects.filter(operator=b, phone="254700999000").exists()


# --- settings + summary API -------------------------------------------------------------


class TestApi:
    def test_defaults_and_update(self):
        op = OperatorFactory()
        body = owner(op).get(SETTINGS).json()
        assert body["is_enabled"] is False
        assert body["spend_per_point"] == 100
        assert body["points_per_threshold"] == 1
        assert body["min_redeem_points"] == 100

        resp = owner(op).patch(
            SETTINGS,
            {"is_enabled": True, "spend_per_point": 50, "value_per_point": "0.50"},
            format="json",
        )
        assert resp.status_code == 200
        row = LoyaltySettings.objects.get(operator=op)
        assert row.is_enabled is True
        assert row.spend_per_point == 50
        assert str(row.value_per_point) == "0.50"

    def test_summary_reports_enrolment_and_top_holders(self):
        op = OperatorFactory()
        _enable(op, spend_per_point=100, points_per_threshold=1)
        award_for_transaction(TransactionFactory(operator=op, amount=1000, phone="254700000001"))
        award_for_transaction(TransactionFactory(operator=op, amount=200, phone="254700000002"))
        body = owner(op).get(SUMMARY).json()
        assert body["accounts"] == 2
        assert body["points_outstanding"] == 12  # 10 + 2
        assert body["top"][0]["phone"] == "254700000001"  # biggest holder first

    def test_settings_are_tenant_isolated(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        owner(a).patch(SETTINGS, {"spend_per_point": 20}, format="json")
        assert owner(b).get(SETTINGS).json()["spend_per_point"] == 100  # B unaffected
