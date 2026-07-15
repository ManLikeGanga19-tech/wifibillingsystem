"""Monthly platform statements: the ISP's itemised record of what we charged them.

The statement must be COMPLETE (every fee, however the sale settled) and HONEST about what
is owed versus already-taken. And it must never double-bill — it reflects the ledger, it
does not re-charge.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.billing import platform_account as pa
from apps.billing.invoicing import build_invoice, settle_outstanding_if_clear
from apps.billing.models import (
    LedgerEntry,
    PlatformInvoice,
    PlatformLedgerEntry,
    Settlement,
)

from .factories import OperatorFactory

pytestmark = pytest.mark.django_db

PERIOD = "2026-06"


def _at(operator, model_kwargs, model=PlatformLedgerEntry):
    """Create a ledger row stamped inside PERIOD (auto_now_add can't be passed, so we
    update created_at after)."""
    row = model.objects.create(operator=operator, **model_kwargs)
    when = timezone.make_aware(datetime(2026, 6, 15, 12, 0))
    model.objects.filter(pk=row.pk).update(created_at=when)
    return row


def fee(operator, amount, reason):
    _at(operator, {"amount": -Decimal(amount), "reason": reason})


# --- the statement is complete and correctly split --------------------------------------


def test_a_statement_itemises_every_fee_for_the_month():
    operator = OperatorFactory(slug="stmt")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()  # clear welcome credit
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)
    fee(operator, "120.00", PlatformLedgerEntry.Reason.PPPOE_FEE)
    fee(operator, "60.00", PlatformLedgerEntry.Reason.COMMISSION)  # direct sale commission
    fee(operator, "40.00", PlatformLedgerEntry.Reason.SMS)

    inv = build_invoice(operator, PERIOD)

    assert inv.base_fee == Decimal("500.00")
    assert inv.pppoe_fee == Decimal("120.00")
    assert inv.direct_commission == Decimal("60.00")
    assert inv.sms == Decimal("40.00")
    # Total DUE excludes the already-withheld aggregator commission (none here).
    assert inv.total == Decimal("720.00")


def test_aggregator_commission_is_shown_as_already_deducted_not_owed():
    """Nothing goes unnoticed — the withheld cut appears on the statement, but it is not
    part of the total due (we already took it)."""
    operator = OperatorFactory(slug="withheld")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)
    # An aggregator sale: commission withheld in the WALLET.
    _at(operator, {"entry_type": LedgerEntry.Type.COMMISSION, "amount": -Decimal("30.00"),
                   "settlement": Settlement.PLATFORM}, model=LedgerEntry)

    inv = build_invoice(operator, PERIOD)

    assert inv.withheld_commission == Decimal("30.00")  # on the statement, for completeness
    assert inv.total == Decimal("500.00")  # but NOT in the amount owed


def test_a_month_with_no_fees_gets_no_statement():
    operator = OperatorFactory(slug="quiet")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()

    assert build_invoice(operator, PERIOD) is None


# --- idempotency: a statement is never duplicated ---------------------------------------


def test_re_running_the_month_does_not_duplicate_the_statement():
    operator = OperatorFactory(slug="idem")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)

    first = build_invoice(operator, PERIOD)
    again = build_invoice(operator, PERIOD)

    assert first.pk == again.pk
    assert PlatformInvoice.objects.filter(operator=operator, period=PERIOD).count() == 1


def test_a_statement_only_counts_ITS_month():
    operator = OperatorFactory(slug="boundary")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)  # in June (PERIOD)
    # A July fee (outside PERIOD) — today's welcome credit etc. also excluded by amount sign.
    pa.accrue_fee(operator, Decimal("999.00"),
                  reason=PlatformLedgerEntry.Reason.BASE_FEE, period="2026-07")

    inv = build_invoice(operator, PERIOD)

    assert inv.total == Decimal("500.00")  # July's 999 is not on June's statement


# --- settlement follows the running account ---------------------------------------------


def test_clearing_the_debt_marks_outstanding_statements_paid():
    operator = OperatorFactory(slug="settle")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)
    inv = build_invoice(operator, PERIOD)
    assert inv.status == PlatformInvoice.Status.OUTSTANDING

    pa.grant(operator, Decimal("500.00"), memo="paid")  # back to zero
    settle_outstanding_if_clear(operator)

    inv.refresh_from_db()
    assert inv.status == PlatformInvoice.Status.PAID
    assert inv.paid_at is not None


def test_a_partial_payment_leaves_the_statement_outstanding():
    """'Paid' can only honestly mean 'you owe us nothing right now'."""
    operator = OperatorFactory(slug="partial")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)
    inv = build_invoice(operator, PERIOD)

    pa.grant(operator, Decimal("200.00"))  # still owes 300
    settle_outstanding_if_clear(operator)

    inv.refresh_from_db()
    assert inv.status == PlatformInvoice.Status.OUTSTANDING


def test_the_statement_does_not_re_charge_the_ledger():
    """It reflects the ledger; it must not move the balance."""
    operator = OperatorFactory(slug="norecharge")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)
    before = pa.balance(operator)

    build_invoice(operator, PERIOD)

    assert pa.balance(operator) == before  # unchanged


def test_the_isp_can_read_their_statements():
    from rest_framework.test import APIClient

    from apps.accounts.models import Role

    from .factories import UserFactory

    operator = OperatorFactory(slug="reader")
    PlatformLedgerEntry.objects.filter(operator=operator).delete()
    fee(operator, "500.00", PlatformLedgerEntry.Reason.BASE_FEE)
    build_invoice(operator, PERIOD)

    client = APIClient()
    client.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    resp = client.get("/api/v1/billing/account/invoices/")

    assert resp.status_code == 200
    assert resp.json()["invoices"][0]["period"] == PERIOD
    assert resp.json()["invoices"][0]["total"] == "500.00"
