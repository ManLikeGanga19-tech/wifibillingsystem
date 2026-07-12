"""Reuniting a mistyped payment with its owner.

A PPPoE customer pays by paybill and fat-fingers the account number. Safaricom has
already taken the money, so we can't refuse it — it lands UNMATCHED, credited to nobody.
Left there, that's a customer who paid and stayed cut off, and an ISP blamed for losing a
payment. This is the queue and the tools that fix it: a suggestion engine to find who it
belongs to, and a resolve action that credits them.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.payments.c2b import process_c2b_confirmation, suggest_clients_for
from apps.payments.models import C2BPayment

from .factories import OperatorFactory, PppoeClientFactory, UserFactory

pytestmark = pytest.mark.django_db


def platform_client():
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=None, is_staff=True, role=Role.PLATFORM_OWNER))
    return c


def make_client(operator, *, account, phone="", name="A Customer"):
    return PppoeClientFactory(
        operator=operator, account_number=account, full_name=name, phone=phone,
        plan__price=Decimal("2000"),
    )


def unmatched(account_typed, *, amount="2000", msisdn="254712345678"):
    return process_c2b_confirmation(
        {"TransID": f"T{account_typed}", "TransAmount": amount,
         "BillRefNumber": account_typed, "MSISDN": msisdn, "FirstName": "Jane"}
    )


class TestUnmatchedLands:
    def test_a_mistyped_account_lands_unmatched_crediting_nobody(self):
        op = OperatorFactory()
        make_client(op, account="ACME001")
        p = unmatched("ACME01")  # typo: missing a zero
        assert p.status == C2BPayment.Status.UNMATCHED
        assert p.operator_id is None
        assert p.client_id is None


class TestSuggestions:
    def test_the_payers_phone_is_the_strongest_signal(self):
        op = OperatorFactory()
        # Two clients; only one shares the payer's phone.
        make_client(op, account="ACME001", phone="254712345678", name="Right One")
        make_client(op, account="ACME002", phone="254700000000", name="Wrong One")
        p = unmatched("ZZZ999", msisdn="254712345678")  # account gibberish, phone matches

        suggestions = suggest_clients_for(p)
        assert suggestions[0][0].full_name == "Right One"
        assert suggestions[0][1] >= 0.9  # high confidence
        assert "254712345678" in suggestions[0][2]

    def test_a_close_account_number_is_suggested(self):
        op = OperatorFactory()
        make_client(op, account="ACME001", phone="")
        p = unmatched("ACME01", msisdn="")  # one char off, no phone signal

        suggestions = suggest_clients_for(p)
        assert any(c.account_number == "ACME001" for c, _, _ in suggestions)


class TestResolution:
    def test_resolving_credits_the_client_and_closes_the_payment(self):
        op = OperatorFactory()  # can_transact True by default
        client = make_client(op, account="ACME001")
        p = unmatched("ACME01")

        resp = platform_client().post(
            f"/api/v1/payments/platform/unmatched/{p.id}/resolve/",
            {"client_id": client.id}, format="json",
        )
        assert resp.status_code == 200, resp.content
        p.refresh_from_db()
        assert p.status == C2BPayment.Status.MATCHED
        assert p.client_id == client.id
        client.refresh_from_db()
        assert client.balance == Decimal("2000")  # credited

    def test_resolving_for_a_not_live_isp_holds_instead_of_credits(self):
        op = OperatorFactory(status=OperatorFactory._meta.model.Status.PENDING,
                             settlement_verified_at=None)
        assert not op.can_transact
        client = make_client(op, account="ACME001")
        p = unmatched("ACME01")

        platform_client().post(
            f"/api/v1/payments/platform/unmatched/{p.id}/resolve/",
            {"client_id": client.id}, format="json",
        )
        p.refresh_from_db()
        assert p.status == C2BPayment.Status.HELD  # money gate still applies
        client.refresh_from_db()
        assert client.balance == Decimal("0")  # not credited until they go live

    def test_an_already_resolved_payment_cannot_be_resolved_twice(self):
        op = OperatorFactory()
        client = make_client(op, account="ACME001")
        p = unmatched("ACME01")
        c = platform_client()
        url = f"/api/v1/payments/platform/unmatched/{p.id}/resolve/"
        assert c.post(url, {"client_id": client.id}, format="json").status_code == 200
        # second attempt: already matched
        assert c.post(url, {"client_id": client.id}, format="json").status_code == 409

    def test_resolution_is_audited(self):
        from apps.core.models import AuditLog

        op = OperatorFactory()
        client = make_client(op, account="ACME001")
        p = unmatched("ACME01")
        platform_client().post(
            f"/api/v1/payments/platform/unmatched/{p.id}/resolve/",
            {"client_id": client.id}, format="json",
        )
        entry = AuditLog.objects.filter(action="c2b_payment_resolved").first()
        assert entry is not None
        assert entry.metadata["typed_account"] == "ACME01"


class TestAccessControl:
    def test_a_tenant_owner_cannot_see_the_queue(self):
        """Unmatched payments have no operator — only the platform can work them."""
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER))
        assert c.get("/api/v1/payments/platform/unmatched/").status_code == 403

    def test_the_queue_lists_unmatched_with_suggestions(self):
        op = OperatorFactory()
        make_client(op, account="ACME001", phone="254712345678")
        unmatched("ACME01", msisdn="254712345678")

        body = platform_client().get("/api/v1/payments/platform/unmatched/").json()
        assert body["count"] == 1
        assert body["results"][0]["typed_account"] == "ACME01"
        assert len(body["results"][0]["suggestions"]) >= 1
