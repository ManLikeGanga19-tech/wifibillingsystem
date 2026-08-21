"""AI billing: the Pro subscription fee accrues to the platform ledger like every other fee,
owner-only self-serve opt-in, and true-margin cost tracking from logged tokens."""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.assistant.costs import ai_cost_kes
from apps.assistant.models import AISettings, AssistantQuestion
from apps.billing.invoicing import build_invoice
from apps.billing.models import PlatformLedgerEntry
from apps.billing.platform_account import balance
from apps.billing.services import charge_ai_pro_fees

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db
PRO_URL = "/api/v1/assistant/pro/"


def as_role(op, role):
    c = APIClient()
    c.force_authenticate(UserFactory(operator=op, is_staff=True, role=role))
    return c


class TestProFeeAccrual:
    def test_pro_tenant_charged_once_per_month(self, settings):
        settings.AI_PRO_MONTHLY_FEE = "1500"
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"pro_ai": True})

        before = balance(op)
        assert charge_ai_pro_fees() == 1
        assert balance(op) == before - Decimal("1500")     # a fee debits the account
        assert charge_ai_pro_fees() == 0                    # idempotent per month

        entry = PlatformLedgerEntry.objects.get(
            operator=op, reason=PlatformLedgerEntry.Reason.AI_PRO)
        assert entry.amount == Decimal("-1500.00")

    def test_free_tenant_is_not_charged(self, settings):
        settings.AI_PRO_MONTHLY_FEE = "1500"
        op = OperatorFactory()
        AISettings.objects.get_or_create(operator=op)       # pro_ai defaults False
        assert charge_ai_pro_fees() == 0

    def test_ai_fee_itemised_on_the_monthly_statement(self, settings):
        settings.AI_PRO_MONTHLY_FEE = "1500"
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"pro_ai": True})
        charge_ai_pro_fees()

        inv = build_invoice(op, timezone.localdate().strftime("%Y-%m"))
        assert inv.ai_fee == Decimal("1500.00")
        assert inv.total >= Decimal("1500.00")


class TestProToggle:
    def test_owner_enables_pro_and_it_is_audited(self, settings):
        from apps.core.models import AuditLog

        settings.AI_PRO_SELF_SERVE = True
        op = OperatorFactory()
        r = as_role(op, Role.TENANT_OWNER).post(PRO_URL, {"enabled": True}, format="json")
        assert r.status_code == 200, r.content
        assert AISettings.objects.get(operator=op).pro_ai is True
        assert r.json()["tier"] == "pro"
        assert AuditLog.objects.filter(operator=op, action="ai_pro_enabled").exists()

    def test_enabling_is_blocked_while_self_serve_is_off(self, settings):
        settings.AI_PRO_SELF_SERVE = False
        op = OperatorFactory()
        r = as_role(op, Role.TENANT_OWNER).post(PRO_URL, {"enabled": True}, format="json")
        assert r.status_code == 403
        assert r.json()["code"] == "pro_unavailable"
        assert not AISettings.objects.filter(operator=op, pro_ai=True).exists()

    def test_care_cannot_toggle_pro(self, settings):
        settings.AI_PRO_SELF_SERVE = True
        op = OperatorFactory()
        r = as_role(op, Role.TENANT_CARE).post(PRO_URL, {"enabled": True}, format="json")
        assert r.status_code == 403          # money.manage is Owner-only

    def test_disable_is_always_allowed(self):
        op = OperatorFactory()
        AISettings.objects.update_or_create(operator=op, defaults={"pro_ai": True})
        # Even with self-serve off (the default), turning it OFF must always work.
        r = as_role(op, Role.TENANT_OWNER).post(PRO_URL, {"enabled": False}, format="json")
        assert r.status_code == 200
        assert AISettings.objects.get(operator=op).pro_ai is False


class TestTrueMargin:
    def test_prices_platform_tiers_and_skips_byo(self, settings):
        settings.AI_MODEL_PRICES = {"claude-haiku-4-5": (1.0, 5.0)}
        settings.AI_USD_TO_KES = 100
        op = OperatorFactory()
        # 1M in + 1M out on Haiku => (1*$1 + 1*$5) * 100 KES = 600
        AssistantQuestion.objects.create(
            operator=op, question="x", tier="free", model="claude-haiku-4-5",
            tokens_in=1_000_000, tokens_out=1_000_000)
        # BYO runs on the tenant's own key — never a platform cost.
        AssistantQuestion.objects.create(
            operator=op, question="y", tier="byo", model="claude-haiku-4-5",
            tokens_in=1_000_000, tokens_out=1_000_000)
        assert ai_cost_kes(op) == Decimal("600.00")
