"""THE MONEY GATE.

A freshly signed-up ISP gets their console immediately — routers, plans, branding,
real work. What they cannot do is take a single shilling until we have verified who
they are.

This is not bureaucracy. WE own the paybill. An unverified business collecting real
customer money through Danamo's shortcode is OUR anti-money-laundering exposure,
not theirs. So every path money can travel is tested here:

  in   : hotspot STK push · voucher redemption · C2B broadband payment
  out  : withdrawal
  serve: provisioning a paying customer
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.services import wallet_balance
from apps.core.models import Operator
from apps.payments.c2b import process_c2b_confirmation
from apps.payments.models import C2BPayment
from apps.plans.models import Plan
from apps.pppoe.models import Client

from .factories import (
    OperatorFactory,
    PlanFactory,
    PppoeClientFactory,
    RouterFactory,
    UserFactory,
    VoucherFactory,
)

pytestmark = pytest.mark.django_db


def pending_isp(**kw):
    """A FRESHLY signed-up ISP: pending, and no settlement account yet.

    The factory's default operator is a normal live trading ISP (verified
    settlement), so these have to be cleared explicitly — otherwise we would be
    testing the gate against an ISP that has already done the work.
    """
    return OperatorFactory(
        status=Operator.Status.PENDING,
        settlement_method="",
        settlement_paybill="",
        settlement_name="",
        settlement_verified_at=None,
        **kw,
    )


def owner_of(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


class TestTheConsoleStaysOpen:
    """"Explore now, money later." A pending ISP must be able to do real work —
    otherwise we have just built a waiting room."""

    def test_a_pending_isp_can_use_their_console(self):
        op = pending_isp()
        c = owner_of(op)
        assert c.get("/api/v1/plans/").status_code == 200
        assert c.get("/api/v1/routers/").status_code == 200
        assert c.get("/api/v1/pppoe/clients/").status_code == 200
        # They can SEE their wallet (it may already hold held payments) — they
        # just cannot withdraw from it.
        assert c.get("/api/v1/billing/wallet/").status_code == 200

    def test_a_pending_isp_can_configure_everything(self):
        op = pending_isp()
        c = owner_of(op)
        resp = c.post(
            "/api/v1/plans/",
            {"name": "1 Hour", "price": "20.00", "duration": "01:00:00",
             "download_kbps": 5120, "upload_kbps": 2048},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert c.post(
            "/api/v1/pppoe/towers/", {"name": "Hill Site"}, format="json"
        ).status_code == 201

    def test_a_SUSPENDED_isp_is_locked_out_entirely(self):
        """Pending is a waiting room with the lights on. Suspended is a locked door."""
        op = OperatorFactory(status=Operator.Status.SUSPENDED)
        c = owner_of(op)
        assert c.get("/api/v1/routers/").status_code == 403


class TestMoneyInIsBlocked:
    def test_the_portal_does_not_offer_a_pending_isps_plans(self):
        """A hotspot whose owner is unverified is NOT LIVE. Showing plans we would
        then refuse to charge for is worse than showing none."""
        op = pending_isp()
        router = RouterFactory(operator=op)
        PlanFactory(operator=op, name="Should Not Appear")

        results = APIClient().get(f"/api/v1/plans/?router={router.id}").json()["results"]
        assert results == []

    def test_stk_push_is_refused_for_a_pending_isp(self):
        op = pending_isp()
        router = RouterFactory(operator=op)
        plan = PlanFactory(operator=op)

        resp = APIClient().post(
            "/api/v1/payments/stk-push/",
            {"phone": "254712345678", "plan_id": plan.id, "router_id": router.id},
            format="json",
        )
        assert resp.status_code == 400, resp.content
        assert "not live" in str(resp.content).lower()

    def test_voucher_redemption_is_refused_for_a_pending_isp(self):
        op = pending_isp()
        router = RouterFactory(operator=op)
        plan = PlanFactory(operator=op)
        voucher = VoucherFactory(operator=op, plan=plan)

        resp = APIClient().post(
            "/api/v1/vouchers/redeem/",
            {"code": voucher.code, "router_id": router.id},
            format="json",
        )
        assert resp.status_code == 400
        assert "not live" in str(resp.content).lower()

    def test_an_active_isp_can_still_sell(self):
        """The gate must not break the working path."""
        op = OperatorFactory(status=Operator.Status.ACTIVE)
        router = RouterFactory(operator=op)
        PlanFactory(operator=op, name="Live Plan", plan_type=Plan.PlanType.HOTSPOT)

        results = APIClient().get(f"/api/v1/plans/?router={router.id}").json()["results"]
        assert [p["name"] for p in results] == ["Live Plan"]


class TestMoneyOutIsBlocked:
    def test_a_pending_isp_cannot_withdraw(self):
        op = pending_isp()
        c = owner_of(op)
        resp = c.post(
            "/api/v1/billing/payouts/withdraw/",
            {"amount": "100.00", "method": "mpesa", "phone": "254712345678"},
            format="json",
        )
        assert resp.status_code == 403
        assert "settlement" in resp.json()["detail"].lower()


class TestProvisioningIsBlocked:
    def test_a_pending_isp_cannot_switch_a_customer_on(self):
        op = pending_isp()
        client = PppoeClientFactory(operator=op, status=Client.Status.PENDING_INSTALL)
        c = owner_of(op)
        resp = c.post(f"/api/v1/pppoe/clients/{client.id}/provision/")
        assert resp.status_code == 403
        client.refresh_from_db()
        assert client.status == Client.Status.PENDING_INSTALL  # still off

    def test_a_pending_isp_can_still_BUILD_their_client_list(self):
        """They can prepare everything — they just cannot go live."""
        op = pending_isp()
        c = owner_of(op)
        from .factories import RouterFactory as RF
        from .factories import ServicePlanFactory

        plan = ServicePlanFactory(operator=op)
        router = RF(operator=op)
        resp = c.post(
            "/api/v1/pppoe/clients/",
            {"full_name": "Future Customer", "plan": plan.id, "router": router.id},
            format="json",
        )
        assert resp.status_code == 201, resp.content


class TestC2BMoneyIsHeldNotLost:
    """We cannot REFUSE a C2B payment — Safaricom has already taken the customer's
    money by the time we hear about it. So it is HELD: recorded, attributed, but not
    credited and not restoring service. Nobody loses a shilling."""

    def _pay(self, client, amount="2000", trans="C2BHELD1"):
        return process_c2b_confirmation(
            {
                "TransID": trans,
                "TransAmount": amount,
                "BillRefNumber": client.account_number,
                "MSISDN": "254712345678",
            }
        )

    def test_a_payment_to_a_pending_isp_is_held_not_credited(self):
        op = pending_isp()
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))

        payment = self._pay(client)

        assert payment.status == C2BPayment.Status.HELD
        assert payment.operator == op  # we know exactly whose it is
        assert wallet_balance(op) == Decimal("0.00")  # but NOT credited

    def test_a_held_payment_does_not_restore_service(self):
        op = pending_isp()
        client = PppoeClientFactory(
            operator=op, status=Client.Status.SUSPENDED, plan__price=Decimal("2000")
        )
        self._pay(client)
        client.refresh_from_db()
        assert client.status == Client.Status.SUSPENDED

    def test_approval_releases_every_held_payment(self):
        """Nobody loses a shilling because WE made them wait."""
        op = pending_isp(slug="held-isp")
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))
        self._pay(client, amount="2000", trans="H1")
        self._pay(client, amount="1500", trans="H2")
        assert wallet_balance(op) == Decimal("0.00")

        admin = APIClient()
        admin.force_authenticate(
            user=UserFactory(
                operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
            )
        )
        resp = admin.post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert resp.status_code == 200
        assert resp.json()["released_payments"] == 2

        assert wallet_balance(op) == Decimal("3500.00")  # both credited
        assert not C2BPayment.objects.filter(status=C2BPayment.Status.HELD).exists()

    def test_releasing_twice_does_not_double_credit(self):
        from apps.payments.c2b import release_held_payments

        op = pending_isp()
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))
        self._pay(client)

        op.status = Operator.Status.ACTIVE
        op.save()
        assert release_held_payments(op) == 1
        assert release_held_payments(op) == 0  # idempotent
        assert wallet_balance(op) == Decimal("2000.00")

    def test_an_active_isp_is_credited_immediately(self):
        op = OperatorFactory(status=Operator.Status.ACTIVE)
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))
        payment = self._pay(client)
        assert payment.status == C2BPayment.Status.MATCHED
        assert wallet_balance(op) == Decimal("2000.00")


class TestC2BValidationRejectsUpFront:
    """Better than holding money: don't take it. With Safaricom's Validation
    callback enabled, we refuse the account BEFORE the customer pays."""

    def _validate(self, account):
        from django.conf import settings
        from django.test import Client as DjangoClient

        return DjangoClient().post(
            f"/api/v1/payments/c2b/validation/{settings.DARAJA_CALLBACK_TOKEN}/",
            data=f'{{"BillRefNumber": "{account}"}}',
            content_type="application/json",
        )

    def test_a_pending_isps_account_is_rejected(self):
        op = pending_isp()
        client = PppoeClientFactory(operator=op)
        body = self._validate(client.account_number).json()
        assert body["ResultCode"] == "C2B00012"  # invalid account
        assert "not active" in body["ResultDesc"].lower()

    def test_an_active_isps_account_is_accepted(self):
        op = OperatorFactory(status=Operator.Status.ACTIVE)
        client = PppoeClientFactory(operator=op)
        body = self._validate(client.account_number).json()
        assert body["ResultCode"] == "0"


class TestTheIspIsToldWhy:
    """A blocked action must never look like a broken product."""

    def test_me_reports_the_gate_and_what_to_do_about_it(self):
        op = pending_isp()
        c = owner_of(op)
        me = c.get("/api/v1/me/").json()

        assert me["operator"]["can_transact"] is False
        # One thing stands between them and trading: somewhere to be paid. That IS
        # the KYC bar — holding a paybill means Safaricom already vetted them.
        blockers = me["operator"]["go_live_blockers"]
        assert [b["key"] for b in blockers] == ["settlement_account"]
        # It tells them what to DO, not just that they can't.
        assert blockers[0]["actionable"] is True
        assert blockers[0]["done"] is False

    def test_a_live_isp_has_no_blockers(self):
        op = OperatorFactory(status=Operator.Status.ACTIVE)
        me = owner_of(op).get("/api/v1/me/").json()
        assert me["operator"]["can_transact"] is True
        assert me["operator"]["go_live_blockers"] == []
