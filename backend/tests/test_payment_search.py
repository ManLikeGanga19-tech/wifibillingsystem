"""Unified payments search: one box across hotspot (STK) transactions AND fixed-line (PPPoE) C2B
payments, matched by phone / M-Pesa code / (PPPoE) account number, tenant-scoped."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.payments.models import C2BPayment

from .factories import OperatorFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/payments/search/"


def staff(operator):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


def _c2b(operator, **kw):
    return C2BPayment.objects.create(
        operator=operator,
        trans_id=kw.get("trans_id", "RKT9ZZZ1"),
        bill_ref=kw.get("bill_ref", "DEFA00620"),
        msisdn=kw.get("msisdn", "254700111222"),
        amount=Decimal(kw.get("amount", "1500")),
        status=C2BPayment.Status.MATCHED,
    )


def _results(op, q):
    return staff(op).get(URL, {"q": q}).json()["results"]


class TestPaymentSearch:
    def test_finds_hotspot_by_phone_then_code_case_insensitive(self):
        op = OperatorFactory()
        TransactionFactory(operator=op, phone="254712345678", mpesa_receipt="QGH7ABC123")
        by_phone = _results(op, "712345")
        assert any(r["kind"] == "hotspot" and r["phone"] == "254712345678" for r in by_phone)
        by_code = _results(op, "qgh7")  # lower-case query still matches
        assert any(r["code"] == "QGH7ABC123" for r in by_code)

    def test_finds_pppoe_by_account_number_and_code(self):
        op = OperatorFactory()
        _c2b(op, bill_ref="DEFA00620", trans_id="RKT9AAA1", msisdn="254701000000")
        by_account = _results(op, "DEFA00620")
        assert any(r["kind"] == "pppoe" and r["reference"] == "DEFA00620" for r in by_account)
        by_code = _results(op, "rkt9aaa1")
        assert any(r["kind"] == "pppoe" and r["code"] == "RKT9AAA1" for r in by_code)

    def test_spans_both_rails_in_one_query(self):
        op = OperatorFactory()
        TransactionFactory(operator=op, phone="254733000000", mpesa_receipt="AAA")
        _c2b(op, msisdn="254733000000", trans_id="BBB", bill_ref="ACC1")
        kinds = {r["kind"] for r in _results(op, "254733000000")}
        assert kinds == {"hotspot", "pppoe"}

    def test_is_tenant_scoped(self):
        mine, theirs = OperatorFactory(slug="mine"), OperatorFactory(slug="theirs")
        TransactionFactory(operator=theirs, phone="254799999999", mpesa_receipt="ZZZ")
        _c2b(theirs, msisdn="254799999999", trans_id="TTT", bill_ref="THEIRS1")
        assert _results(mine, "254799999999") == []

    def test_a_too_short_query_returns_nothing(self):
        op = OperatorFactory()
        TransactionFactory(operator=op, phone="254712345678")
        assert _results(op, "7") == []
