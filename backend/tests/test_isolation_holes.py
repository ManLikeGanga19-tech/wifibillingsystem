"""Regression tests for the 5 cross-tenant holes found in the isolation audit.
Each test would have PASSED (i.e. the leak worked) before the fix."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, Subscriber
from apps.ops.models import Expense, Ticket
from apps.provisioning.models import Session

from .factories import (
    OperatorFactory,
    PlanFactory,
    RouterFactory,
    UserFactory,
    VoucherFactory,
)

pytestmark = pytest.mark.django_db


def staff(operator):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


@pytest.fixture
def a_and_b(db):
    return (
        OperatorFactory(slug="hole-a", name="A"),
        OperatorFactory(slug="hole-b", name="B"),
    )


class TestHole1VoucherForeignRouter:
    def test_voucher_cannot_provision_on_another_tenants_router(self, a_and_b):
        op_a, op_b = a_and_b
        RouterFactory(operator=op_a)  # A's own router (fallback target)
        router_b = RouterFactory(operator=op_b)  # B's physical router
        voucher = VoucherFactory(operator=op_a)

        resp = APIClient().post(
            "/api/v1/vouchers/redeem/",
            {"code": voucher.code, "router_id": router_b.id},
        )
        assert resp.status_code == 201  # redemption still works
        session = Session.objects.get(voucher=voucher)
        # ...but it must NOT have landed on tenant B's router
        assert session.router.operator_id == op_a.id
        assert session.router_id != router_b.id


class TestHole2TicketForeignSubscriber:
    def test_cannot_attach_another_tenants_subscriber(self, a_and_b):
        op_a, op_b = a_and_b
        sub_b = Subscriber.objects.create(operator=op_b, phone="254799000001", name="B's customer")

        resp = staff(op_a).post(
            "/api/v1/ops/tickets/",
            {"subject": "x", "priority": "normal", "subscriber": sub_b.id},
            format="json",
        )
        # The foreign subscriber id must be rejected, not silently bound + echoed.
        assert resp.status_code == 400
        assert not Ticket.objects.filter(subscriber=sub_b).exists()

    def test_own_subscriber_is_accepted(self, a_and_b):
        op_a, _ = a_and_b
        sub_a = Subscriber.objects.create(operator=op_a, phone="254799000002")
        resp = staff(op_a).post(
            "/api/v1/ops/tickets/",
            {"subject": "ok", "priority": "normal", "subscriber": sub_a.id},
            format="json",
        )
        assert resp.status_code == 201


class TestHole3ExpenseEquipmentForeignRouter:
    def test_expense_rejects_foreign_router(self, a_and_b):
        op_a, op_b = a_and_b
        router_b = RouterFactory(operator=op_b)
        resp = staff(op_a).post(
            "/api/v1/ops/expenses/",
            {"date": "2026-07-11", "category": "power", "description": "x",
             "amount": "100.00", "router": router_b.id},
            format="json",
        )
        assert resp.status_code == 400
        assert not Expense.objects.filter(router=router_b).exists()

    def test_equipment_rejects_foreign_router(self, a_and_b):
        op_a, op_b = a_and_b
        router_b = RouterFactory(operator=op_b)
        resp = staff(op_a).post(
            "/api/v1/ops/equipment/",
            {"name": "x", "equipment_type": "router", "router": router_b.id},
            format="json",
        )
        assert resp.status_code == 400


class TestHole4TicketForeignAssignee:
    def test_cannot_assign_to_another_tenants_staff(self, a_and_b):
        op_a, op_b = a_and_b
        staff_b = UserFactory(operator=op_b, is_staff=True)
        resp = staff(op_a).post(
            "/api/v1/ops/tickets/",
            {"subject": "x", "priority": "normal", "assigned_to": staff_b.id},
            format="json",
        )
        assert resp.status_code == 400


class TestHole5StkPushArbitraryPlan:
    def test_stk_push_without_tenant_context_rejected(self, a_and_b):
        op_a, _ = a_and_b
        plan_a = PlanFactory(operator=op_a, price=Decimal("20.00"))
        # No subdomain, no router -> cannot determine ISP -> reject
        resp = APIClient().post(
            "/api/v1/payments/stk-push/",
            {"phone": "0712345678", "plan_id": plan_a.id},
            format="json",
        )
        assert resp.status_code == 400

    def test_stk_push_with_router_context_works(self, a_and_b, mocker):
        op_a, _ = a_and_b
        plan_a = PlanFactory(operator=op_a, price=Decimal("20.00"))
        router_a = RouterFactory(operator=op_a)
        mocker.patch(
            "apps.payments.daraja.DarajaClient.stk_push",
            return_value={"CheckoutRequestID": "ws_CO_iso", "MerchantRequestID": "m"},
        )
        mocker.patch("apps.payments.daraja.DarajaClient.__init__", return_value=None)
        resp = APIClient().post(
            "/api/v1/payments/stk-push/",
            {"phone": "0712345678", "plan_id": plan_a.id, "router_id": router_a.id},
            format="json",
        )
        assert resp.status_code == 201

    def test_stk_push_router_from_other_tenant_cannot_buy_this_plan(self, a_and_b):
        """Router of tenant B + plan of tenant A -> tenant resolves to B, plan A
        is not in B's catalogue -> rejected."""
        op_a, op_b = a_and_b
        plan_a = PlanFactory(operator=op_a, price=Decimal("20.00"))
        router_b = RouterFactory(operator=op_b)
        resp = APIClient().post(
            "/api/v1/payments/stk-push/",
            {"phone": "0712345678", "plan_id": plan_a.id, "router_id": router_b.id},
            format="json",
        )
        assert resp.status_code == 400
