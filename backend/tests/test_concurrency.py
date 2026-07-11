"""Concurrency sanity for the money-critical paths, using REAL threads against a
shared Postgres row (transaction=True so threads see each other's commits).

These guard the two races that matter:
  - Safaricom firing the same callback many times in parallel (must credit once)
  - two devices redeeming the same voucher at the same instant (single use)
"""

import json
import threading
from decimal import Decimal

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client
from django.urls import reverse

from apps.billing.models import LedgerEntry
from apps.billing.services import wallet_balance
from apps.payments.models import Transaction
from apps.provisioning.models import Session
from apps.vouchers.models import Voucher

from .factories import RouterFactory, TransactionFactory, VoucherFactory


def _run_parallel(target, n):
    """Run target() in n threads; each thread closes its DB connections after."""
    barrier = threading.Barrier(n)
    errors = []

    def wrapped():
        try:
            barrier.wait()  # maximise real overlap
            target()
        except Exception as exc:  # pragma: no cover - surfaced via errors list
            errors.append(exc)
        finally:
            for conn in connections.all():
                conn.close()

    threads = [threading.Thread(target=wrapped) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


@pytest.mark.django_db(transaction=True)
class TestCallbackStorm:
    def test_20_parallel_identical_callbacks_credit_once(self):
        router = RouterFactory()
        tx = TransactionFactory(operator=router.operator, amount=Decimal("100.00"))
        payload = json.dumps(
            {
                "Body": {
                    "stkCallback": {
                        "CheckoutRequestID": tx.checkout_request_id,
                        "ResultCode": 0,
                        "ResultDesc": "ok",
                        "CallbackMetadata": {
                            "Item": [
                                {"Name": "Amount", "Value": 100.0},
                                {"Name": "MpesaReceiptNumber", "Value": "STORMRCPT1"},
                            ]
                        },
                    }
                }
            }
        )
        url = reverse("daraja-callback", args=[settings.DARAJA_CALLBACK_TOKEN])

        def fire():
            Client().post(url, data=payload, content_type="application/json")

        errors = _run_parallel(fire, 20)
        assert not errors, errors

        tx.refresh_from_db()
        assert tx.status == Transaction.Status.SUCCESS
        # Exactly one sale + one commission line despite 20 concurrent callbacks
        assert LedgerEntry.objects.filter(transaction=tx, entry_type="sale").count() == 1
        assert LedgerEntry.objects.filter(transaction=tx, entry_type="commission").count() == 1
        assert wallet_balance(router.operator) == Decimal("97.00")
        assert Session.objects.filter(transaction=tx).count() == 1


@pytest.mark.django_db(transaction=True)
class TestVoucherRace:
    def test_one_voucher_ten_parallel_redemptions_single_use(self):
        router = RouterFactory()
        voucher = VoucherFactory(operator=router.operator)
        url = "/api/v1/vouchers/redeem/"
        results = []

        def redeem():
            resp = Client().post(url, data={"code": voucher.code})
            results.append(resp.status_code)

        errors = _run_parallel(redeem, 10)
        assert not errors, errors

        voucher.refresh_from_db()
        assert voucher.status == Voucher.Status.REDEEMED
        # Exactly one success (201), the rest rejected (400). Never two sessions.
        assert results.count(201) == 1, results
        assert Session.objects.filter(voucher=voucher).count() == 1
