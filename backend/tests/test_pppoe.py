"""PPPoE / broadband: account numbers, provisioning, invoicing (anniversary),
C2B payment matching + idempotency, suspend/restore, AP capacity, isolation."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.billing.services import charge_pppoe_user_fees, wallet_balance
from apps.payments.c2b import process_c2b_confirmation
from apps.payments.models import C2BPayment
from apps.pppoe.models import Client, Invoice, generate_account_number
from apps.pppoe.services import (
    create_client,
    issue_invoice,
    provision_client,
    record_client_payment,
    restore_client,
    suspend_client,
)
from apps.provisioning.adapters.dummy import DummyAdapter

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    RouterFactory,
    ServicePlanFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def staff(operator):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


class TestAccountNumber:
    def test_globally_unique_across_operators(self):
        op_a = OperatorFactory(slug="isp-a")
        op_b = OperatorFactory(slug="isp-b")
        nums = {generate_account_number(op_a) for _ in range(20)}
        nums |= {generate_account_number(op_b) for _ in range(20)}
        assert len(nums) == 40  # no collisions

    def test_prefix_from_slug(self):
        op = OperatorFactory(slug="homelink")
        assert generate_account_number(op).startswith("HOME")


class TestProvisioning:
    def test_create_and_provision_pushes_to_router(self):
        router = RouterFactory()
        plan = ServicePlanFactory(operator=router.operator)
        DummyAdapter.calls = []
        client = create_client(
            operator=router.operator, plan=plan, router=router, full_name="Jane Doe"
        )
        assert client.account_number
        assert client.pppoe_username and client.pppoe_password
        provision_client(client)
        client.refresh_from_db()
        assert client.status == Client.Status.ACTIVE
        assert ("ensure_profile", plan.mikrotik_profile) in DummyAdapter.calls
        assert ("pppoe_create", client.pppoe_username) in DummyAdapter.calls

    def test_suspend_and_restore(self):
        client = PppoeClientFactory()
        DummyAdapter.calls = []
        suspend_client(client)
        assert client.status == Client.Status.SUSPENDED
        assert ("pppoe_suspend", client.pppoe_username) in DummyAdapter.calls
        restore_client(client)
        assert client.status == Client.Status.ACTIVE
        assert ("pppoe_enable", client.pppoe_username) in DummyAdapter.calls


class TestInvoicing:
    def test_issue_invoice_is_idempotent_per_period(self):
        client = PppoeClientFactory(plan__price=Decimal("2000.00"))
        today = timezone.localdate()
        inv1 = issue_invoice(client, today)
        inv2 = issue_invoice(client, today)
        assert inv1.pk == inv2.pk
        assert Invoice.objects.filter(client=client).count() == 1
        client.refresh_from_db()
        assert client.balance == Decimal("-2000.00")  # owes one month

    def test_overdue_suspend_flow(self):
        from apps.pppoe.tasks import suspend_overdue_clients

        client = PppoeClientFactory(plan__price=Decimal("2000.00"))
        # an overdue, unpaid invoice
        inv = issue_invoice(client, timezone.localdate() - timedelta(days=40))
        Invoice.objects.filter(pk=inv.pk).update(due_date=timezone.localdate() - timedelta(days=10))
        DummyAdapter.calls = []
        assert suspend_overdue_clients() == 1
        client.refresh_from_db()
        assert client.status == Client.Status.SUSPENDED


class TestC2BPayment:
    def _payload(self, account, amount="2000", trans="ABC123"):
        return {
            "TransID": trans,
            "TransAmount": amount,
            "BillRefNumber": account,
            "MSISDN": "254712345678",
            "FirstName": "JANE",
        }

    def test_payment_credits_wallet_and_settles_invoice(self):
        client = PppoeClientFactory(plan__price=Decimal("2000.00"))
        issue_invoice(client, timezone.localdate())  # balance -2000
        process_c2b_confirmation(self._payload(client.account_number))
        client.refresh_from_db()
        assert client.balance == Decimal("0.00")
        assert client.invoices.first().status == Invoice.Status.PAID
        assert wallet_balance(client.operator) == Decimal("2000.00")  # full, no commission

    def test_c2b_is_idempotent_on_transid(self):
        client = PppoeClientFactory(plan__price=Decimal("2000.00"))
        p = self._payload(client.account_number)
        process_c2b_confirmation(p)
        process_c2b_confirmation(p)
        process_c2b_confirmation(p)
        assert C2BPayment.objects.filter(trans_id="ABC123").count() == 1
        assert wallet_balance(client.operator) == Decimal("2000.00")  # credited once

    def test_payment_restores_suspended_client(self):
        client = PppoeClientFactory(plan__price=Decimal("2000.00"), status=Client.Status.SUSPENDED)
        issue_invoice(client, timezone.localdate())
        DummyAdapter.calls = []
        process_c2b_confirmation(self._payload(client.account_number))
        client.refresh_from_db()
        assert client.status == Client.Status.ACTIVE
        assert ("pppoe_enable", client.pppoe_username) in DummyAdapter.calls

    def test_unmatched_account_recorded_not_lost(self):
        payment = process_c2b_confirmation(self._payload("NOSUCHACC"))
        assert payment.status == C2BPayment.Status.UNMATCHED
        assert payment.client is None

    def test_confirmation_endpoint_always_200(self):
        from django.conf import settings

        client = PppoeClientFactory(plan__price=Decimal("2000.00"))
        url = f"/api/v1/payments/c2b/confirmation/{settings.DARAJA_CALLBACK_TOKEN}/"
        resp = APIClient().post(
            url, data=json.dumps(self._payload(client.account_number)),
            content_type="application/json",
        )
        assert resp.status_code == 200


class TestPlatformFee:
    def test_per_user_fee_charged_monthly(self):
        op = OperatorFactory(pppoe_user_fee=Decimal("50.00"))
        PppoeClientFactory.create_batch(3, operator=op, status=Client.Status.ACTIVE)
        PppoeClientFactory(operator=op, status=Client.Status.DISABLED)  # not billable
        assert charge_pppoe_user_fees() == 1
        # 3 active users x 50 = 150 debit
        fee = LedgerEntry.objects.filter(operator=op, entry_type="pppoe_fee").first()
        assert fee.amount == Decimal("-150.00")

    def test_platform_owned_isp_exempt(self):
        op = OperatorFactory(pppoe_user_fee=Decimal("50.00"), is_platform_owned=True)
        PppoeClientFactory.create_batch(3, operator=op)
        assert charge_pppoe_user_fees() == 0


class TestApiAndIsolation:
    def test_client_create_via_api_generates_account(self):
        op = OperatorFactory()
        plan = ServicePlanFactory(operator=op)
        router = RouterFactory(operator=op)
        resp = staff(op).post(
            "/api/v1/pppoe/clients/",
            {"full_name": "New Client", "plan": plan.id, "router": router.id,
             "delivery_method": "fibre", "billing_day": 5},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()["account_number"]

    def test_clients_are_tenant_isolated(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        PppoeClientFactory(operator=op_a)
        PppoeClientFactory(operator=op_b)
        assert staff(op_a).get("/api/v1/pppoe/clients/").json()["count"] == 1

    def test_cannot_assign_another_tenants_plan(self):
        op_a, op_b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        plan_b = ServicePlanFactory(operator=op_b)
        router_a = RouterFactory(operator=op_a)
        resp = staff(op_a).post(
            "/api/v1/pppoe/clients/",
            {"full_name": "X", "plan": plan_b.id, "router": router_a.id},
            format="json",
        )
        assert resp.status_code == 400  # foreign plan rejected

    def test_access_point_utilization(self):
        op = OperatorFactory()
        from apps.pppoe.models import AccessPoint, Tower

        tower = Tower.objects.create(operator=op, name="Tower 1")
        ap = AccessPoint.objects.create(operator=op, tower=tower, name="Sector A", capacity=10)
        PppoeClientFactory.create_batch(
            4, operator=op, access_point=ap, status=Client.Status.ACTIVE
        )
        data = staff(op).get("/api/v1/pppoe/access-points/").json()["results"][0]
        assert data["client_count"] == 4
        assert data["utilization"] == 40


class TestReconciliation:
    def test_platform_reconciliation(self):
        op = OperatorFactory()
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000.00"))
        record_client_payment(client, Decimal("2000.00"), source="test")
        admin = UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        c = APIClient()
        c.force_authenticate(user=admin)
        data = c.get("/api/v1/platform/reconciliation/").json()
        assert data["scope"] == "all_isps"
        assert Decimal(str(data["owed_to_isps"])) == Decimal("2000.00")
