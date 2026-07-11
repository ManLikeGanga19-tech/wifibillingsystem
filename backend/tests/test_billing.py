"""Wallet engine: commission-at-source, idempotency, payout lifecycle."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.billing.models import LedgerEntry, Payout
from apps.billing.services import (
    WalletError,
    charge_monthly_base_fees,
    credit_sale,
    mark_payout_paid,
    reject_payout,
    request_payout,
    wallet_balance,
)
from apps.core.models import Operator
from apps.payments.models import Transaction

from .factories import OperatorFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def paid_tx(operator):
    tx = TransactionFactory(operator=operator, amount=Decimal("100.00"))
    tx.status = Transaction.Status.SUCCESS
    tx.save()
    return tx


class TestCommissionAtSource:
    def test_sale_credits_gross_minus_commission(self, operator, paid_tx):
        operator.hotspot_commission_pct = Decimal("3.00")
        operator.save()
        credit_sale(paid_tx)

        assert wallet_balance(operator) == Decimal("97.00")
        entries = LedgerEntry.objects.filter(transaction=paid_tx)
        assert entries.get(entry_type=LedgerEntry.Type.SALE).amount == Decimal("100.00")
        assert entries.get(entry_type=LedgerEntry.Type.COMMISSION).amount == Decimal("-3.00")

    def test_replayed_credit_is_idempotent(self, operator, paid_tx):
        credit_sale(paid_tx)
        credit_sale(paid_tx)
        credit_sale(paid_tx)
        assert LedgerEntry.objects.filter(transaction=paid_tx).count() == 2

    def test_commission_rounding(self, operator):
        operator.hotspot_commission_pct = Decimal("2.50")
        operator.save()
        tx = TransactionFactory(operator=operator, amount=Decimal("33.00"))
        credit_sale(tx)
        # 33 * 2.5% = 0.825 -> 0.83 (half-up)
        commission = LedgerEntry.objects.get(
            transaction=tx, entry_type=LedgerEntry.Type.COMMISSION
        )
        assert commission.amount == Decimal("-0.83")

    def test_callback_path_credits_wallet(self, api_client, router):
        """The full flow: M-Pesa callback -> success -> wallet credited once."""
        import json

        from django.conf import settings

        tx = TransactionFactory(operator=router.operator, amount=Decimal("50.00"))
        payload = {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": tx.checkout_request_id,
                    "ResultCode": 0,
                    "ResultDesc": "ok",
                    "CallbackMetadata": {
                        "Item": [
                            {"Name": "Amount", "Value": 50.0},
                            {"Name": "MpesaReceiptNumber", "Value": "ABC123XYZ"},
                        ]
                    },
                }
            }
        }
        url = f"/api/v1/payments/callback/{settings.DARAJA_CALLBACK_TOKEN}/"
        api_client.post(url, data=json.dumps(payload), content_type="application/json")
        api_client.post(url, data=json.dumps(payload), content_type="application/json")

        assert LedgerEntry.objects.filter(transaction=tx).count() == 2  # not 4
        assert wallet_balance(router.operator) == Decimal("48.50")  # 50 - 3%


class TestPayouts:
    def _fund(self, operator, amount="1000.00"):
        tx = TransactionFactory(operator=operator, amount=Decimal(amount))
        operator.hotspot_commission_pct = Decimal("0.00")
        operator.save()
        credit_sale(tx)

    def _mpesa(self, operator, amount, user):
        return request_payout(
            operator=operator, amount=amount, user=user,
            method="mpesa", destination={"phone": "254712345678"},
        )

    def test_withdraw_holds_funds_immediately(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        payout = self._mpesa(operator, Decimal("400.00"), user)
        assert payout.status == Payout.Status.REQUESTED
        assert wallet_balance(operator) == Decimal("600.00")

    def test_bank_withdrawal_captures_details(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        payout = request_payout(
            operator=operator, amount=Decimal("400.00"), user=user, method="bank",
            destination={
                "bank_name": "I&M Bank", "bank_account_number": "12345678",
                "bank_account_name": "My WISP Ltd",
            },
        )
        assert payout.method == Payout.Method.BANK
        assert payout.bank_account_number == "12345678"
        assert "I&M Bank" in payout.destination
        assert wallet_balance(operator) == Decimal("600.00")  # held the same way

    def test_bank_withdrawal_requires_account(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        with pytest.raises(WalletError, match="Bank name and account"):
            request_payout(
                operator=operator, amount=Decimal("400.00"), user=user, method="bank",
                destination={"bank_name": "I&M Bank"},  # missing account number
            )

    def test_withdraw_over_balance_rejected(self, operator):
        self._fund(operator, "200.00")
        user = UserFactory(operator=operator, is_staff=True)
        with pytest.raises(WalletError, match="exceeds"):
            self._mpesa(operator, Decimal("300.00"), user)

    def test_minimum_payout_enforced(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        with pytest.raises(WalletError, match="Minimum"):
            self._mpesa(operator, Decimal("50.00"), user)

    def test_mark_paid(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        payout = self._mpesa(operator, Decimal("500.00"), user)
        admin = UserFactory(operator=None, is_staff=True, is_superuser=True)
        mark_payout_paid(payout, by=admin, mpesa_reference="QGH12345")
        payout.refresh_from_db()
        assert payout.status == Payout.Status.PAID
        assert wallet_balance(operator) == Decimal("500.00")  # debit stays

    def test_reject_refunds(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        payout = self._mpesa(operator, Decimal("500.00"), user)
        admin = UserFactory(operator=None, is_staff=True, is_superuser=True)
        reject_payout(payout, by=admin, note="wrong number")
        assert wallet_balance(operator) == Decimal("1000.00")  # funds returned

    def test_double_processing_blocked(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        payout = self._mpesa(operator, Decimal("500.00"), user)
        admin = UserFactory(operator=None, is_staff=True, is_superuser=True)
        mark_payout_paid(payout, by=admin, mpesa_reference="QGH12345")
        with pytest.raises(WalletError, match="already"):
            reject_payout(payout, by=admin, note="oops")

    def test_withdraw_api(self, operator):
        self._fund(operator)
        user = UserFactory(operator=operator, is_staff=True)
        client = APIClient()
        client.force_authenticate(user=user)
        resp = client.post(
            "/api/v1/billing/payouts/withdraw/",
            {"amount": "250.00", "method": "mpesa", "phone": "0712345678"},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        summary = client.get("/api/v1/billing/wallet/").json()
        assert Decimal(str(summary["balance"])) == Decimal("750.00")


class TestBaseFee:
    def test_monthly_fee_deducted_once(self, operator):
        operator.base_fee = Decimal("1500.00")
        operator.status = Operator.Status.ACTIVE
        operator.save()
        assert charge_monthly_base_fees() == 1
        assert charge_monthly_base_fees() == 0  # same month, no double charge
        assert wallet_balance(operator) == Decimal("-1500.00")

    def test_zero_fee_tenants_skipped(self, db):
        OperatorFactory(slug="freebie", base_fee=Decimal("0.00"))
        assert charge_monthly_base_fees() == 0
