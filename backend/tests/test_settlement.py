"""Settlement accounts and micro-transfer verification — the KYC bar.

The ISP's paybill/bank is where WE pay THEM. It is not a collection account and
customers never touch it. Its real job is KYC: to be issued a paybill or a business
bank account, Safaricom/the bank already ran full identity checks on that business,
so we inherit them for free. A shell company cannot produce one.

But anyone can TYPE "123456". So we prove control the way banks do — send a few
shillings carrying a random reference and ask them to read it back off their own
statement. That is what these tests defend.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import Operator
from apps.core.settlement import MAX_ATTEMPTS, REF_PREFIX
from apps.payments.models import C2BPayment

from .factories import OperatorFactory, PppoeClientFactory, UserFactory

pytestmark = pytest.mark.django_db

SET = "/api/v1/operator/settlement/"
SEND = "/api/v1/operator/settlement/send/"
VERIFY = "/api/v1/operator/settlement/verify/"

PAYBILL = {"method": "paybill", "settlement_paybill": "555777", "settlement_name": "Acme Ltd"}


def unverified_isp(**kw):
    """A freshly signed-up ISP: pending, no settlement account."""
    return OperatorFactory(
        status=Operator.Status.PENDING,
        settlement_method="",
        settlement_paybill="",
        settlement_name="",
        settlement_verified_at=None,
        **kw,
    )


def owner_of(operator, role=Role.TENANT_OWNER):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=role))
    return c


def ref_of(operator) -> str:
    operator.refresh_from_db()
    return operator.verification_ref


class TestSettingTheAccount:
    def test_an_isp_registers_a_paybill(self):
        op = unverified_isp()
        resp = owner_of(op).post(SET, PAYBILL, format="json")
        assert resp.status_code == 201, resp.content

        op.refresh_from_db()
        assert op.settlement_method == Operator.Settlement.PAYBILL
        assert op.settlement_paybill == "555777"
        assert op.has_settlement_account
        assert not op.can_transact  # registering is not proving

    def test_an_isp_registers_a_bank_account(self):
        op = unverified_isp()
        resp = owner_of(op).post(
            SET,
            {
                "method": "bank",
                "payout_bank_name": "I&M Bank",
                "payout_bank_account_number": "0123456789",
                "payout_bank_account_name": "Acme Ltd",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content
        op.refresh_from_db()
        assert op.has_settlement_account

    def test_a_paybill_must_be_digits(self):
        op = unverified_isp()
        resp = owner_of(op).post(
            SET, {**PAYBILL, "settlement_paybill": "not-a-paybill"}, format="json"
        )
        assert resp.status_code == 400

    def test_changing_the_account_RESETS_verification(self):
        """Otherwise an ISP could verify an account they control, then quietly swap
        in one they don't — and we'd pay a stranger."""
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        c.post(SEND)
        c.post(VERIFY, {"reference": ref_of(op)}, format="json")
        op.refresh_from_db()
        assert op.settlement_verified_at is not None

        c.post(SET, {**PAYBILL, "settlement_paybill": "999888"}, format="json")
        op.refresh_from_db()
        assert op.settlement_verified_at is None  # must be proved again
        assert op.verification_ref == ""

    def test_only_the_OWNER_may_set_it(self):
        """Setting the destination IS withdrawing, one step removed."""
        op = unverified_isp()
        c = owner_of(op, role=Role.TENANT_SUPPORT)
        assert c.post(SET, PAYBILL, format="json").status_code == 403


class TestMicroTransfer:
    def test_sending_mints_a_reference_and_an_amount(self):
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")

        resp = c.post(SEND)
        assert resp.status_code == 200, resp.content

        op.refresh_from_db()
        assert op.verification_ref.startswith(REF_PREFIX)
        assert Decimal("5.00") <= op.verification_amount <= Decimal("19.00")
        assert op.verification_sent_at

    def test_the_reference_is_NEVER_returned_over_the_api(self):
        """The entire proof is that only someone who can see the destination
        account's statement learns it. Leaking it here would make the whole
        mechanism theatre."""
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        body = c.post(SEND).json()

        assert ref_of(op) not in str(body)
        # ...but the AMOUNT is shown, so they can find the row on their statement.
        assert body["verification"]["amount"]

    def test_the_state_endpoint_never_leaks_it_either(self):
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        c.post(SEND)
        assert ref_of(op) not in str(c.get(SET).json())

    def test_you_cannot_send_without_an_account(self):
        op = unverified_isp()
        assert owner_of(op).post(SEND).status_code == 400

    def test_the_reference_uses_an_unambiguous_alphabet(self):
        """They read this off an SMS and type it back. Every O/0 or I/1 is a
        support ticket."""
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        c.post(SEND)
        code = ref_of(op)[len(REF_PREFIX):]
        assert not (set(code) & set("O0I1S5"))


class TestVerification:
    def _ready(self):
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        c.post(SEND)
        return op, c

    def test_the_right_reference_switches_payments_ON(self):
        op, c = self._ready()
        assert op.can_transact is False

        resp = c.post(VERIFY, {"reference": ref_of(op)}, format="json")
        assert resp.status_code == 200, resp.content

        op.refresh_from_db()
        assert op.settlement_verified_at is not None
        assert op.status == Operator.Status.ACTIVE  # auto-activated, no human needed
        assert op.can_transact is True
        assert op.trial_ends_at is not None  # the free month starts when they can EARN

    def test_it_is_accepted_without_the_prefix(self):
        """They'll type just the code half the time. Don't punish them for it."""
        op, c = self._ready()
        bare = ref_of(op)[len(REF_PREFIX):]
        assert c.post(VERIFY, {"reference": bare}, format="json").status_code == 200
        op.refresh_from_db()
        assert op.can_transact

    def test_it_is_case_and_space_insensitive(self):
        op, c = self._ready()
        messy = f" {ref_of(op).lower()} "
        assert c.post(VERIFY, {"reference": messy}, format="json").status_code == 200

    def test_a_wrong_reference_is_counted(self):
        op, c = self._ready()
        resp = c.post(VERIFY, {"reference": "WOS-ZZZZ"}, format="json")
        assert resp.status_code == 400
        op.refresh_from_db()
        assert op.verification_attempts == 1
        assert op.settlement_verified_at is None

    def test_it_cannot_be_brute_forced(self):
        op, c = self._ready()
        for _ in range(MAX_ATTEMPTS):
            c.post(VERIFY, {"reference": "WOS-ZZZZ"}, format="json")

        # Even the RIGHT reference no longer works — the challenge is spent.
        resp = c.post(VERIFY, {"reference": ref_of(op)}, format="json")
        assert resp.status_code == 400
        assert "new transfer" in resp.json()["detail"].lower()
        op.refresh_from_db()
        assert op.can_transact is False

    def test_a_stale_challenge_is_refused(self):
        op, c = self._ready()
        Operator.objects.filter(pk=op.pk).update(
            verification_sent_at=timezone.now() - timedelta(days=5)
        )
        resp = c.post(VERIFY, {"reference": ref_of(op)}, format="json")
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_you_cannot_verify_before_anything_was_sent(self):
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        assert c.post(VERIFY, {"reference": "WOS-ABCD"}, format="json").status_code == 400

    def test_verifying_twice_is_harmless(self):
        op, c = self._ready()
        ref = ref_of(op)
        assert c.post(VERIFY, {"reference": ref}, format="json").status_code == 200
        assert c.post(VERIFY, {"reference": ref}, format="json").status_code == 200


class TestVerificationReleasesHeldMoney:
    def test_going_live_credits_everything_customers_paid_while_waiting(self):
        op = unverified_isp()
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))

        from apps.payments.c2b import process_c2b_confirmation

        process_c2b_confirmation(
            {"TransID": "SET1", "TransAmount": "2000",
             "BillRefNumber": client.account_number, "MSISDN": "254712345678"}
        )
        from apps.billing.services import wallet_balance

        assert wallet_balance(op) == Decimal("0.00")
        assert C2BPayment.objects.get(trans_id="SET1").status == C2BPayment.Status.HELD

        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        c.post(SEND)
        c.post(VERIFY, {"reference": ref_of(op)}, format="json")

        # Nobody loses a shilling because WE made them wait.
        assert wallet_balance(op) == Decimal("2000.00")
        assert C2BPayment.objects.get(trans_id="SET1").status == C2BPayment.Status.MATCHED


class TestDefenceInDepth:
    def test_an_ACTIVE_isp_with_no_verified_settlement_still_cannot_transact(self):
        """The gate must not hang on a single flag. If anyone ever flips status to
        active by hand — in the admin, or straight in the database — money still
        does not move for a business we have not proved out."""
        op = OperatorFactory(
            status=Operator.Status.ACTIVE,
            settlement_verified_at=None,
            settlement_method="",
            settlement_paybill="",
        )
        assert op.status == Operator.Status.ACTIVE
        assert op.can_transact is False

    def test_the_platforms_own_isp_is_exempt(self):
        """Settling to ourselves is meaningless."""
        op = OperatorFactory(
            status=Operator.Status.ACTIVE,
            is_platform_owned=True,
            settlement_verified_at=None,
            settlement_method="",
        )
        assert op.can_transact is True

    def test_manual_approval_alone_does_not_open_the_money_gate(self, settings):
        """A platform admin can activate an ISP — but that is not the same as
        proving who they are."""
        op = unverified_isp()
        admin = APIClient()
        admin.force_authenticate(
            user=UserFactory(
                operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
            )
        )
        resp = admin.post(f"/api/v1/platform/tenants/{op.id}/approve/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        assert resp.json()["can_transact"] is False  # still no verified settlement
        assert resp.json()["settlement_verified"] is False


class TestForcedManualReview:
    def test_verification_does_not_auto_activate_when_review_is_forced(self, settings):
        settings.SETTLEMENT_REQUIRES_MANUAL_REVIEW = True
        op = unverified_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        c.post(SEND)
        c.post(VERIFY, {"reference": ref_of(op)}, format="json")

        op.refresh_from_db()
        assert op.settlement_verified_at is not None  # proved
        assert op.status == Operator.Status.PENDING  # but a human must still say yes
        assert op.can_transact is False


class TestTheSuspendedNoticeBug:
    """🔴 The page told a cut-off subscriber to pay the ISP'S OWN paybill. C2B
    confirmations only ever arrive at DANAMO's shortcode — so anyone who followed
    those instructions either paid the ISP directly (we never saw it, and they
    STAYED CUT OFF despite having paid) or was shown no paybill at all."""

    def test_it_shows_DANAMOS_paybill_and_the_routing_account_number(self, settings):
        settings.DARAJA_SHORTCODE = "4123456"
        op = OperatorFactory(slug="isp", name="Some ISP")
        from .factories import RouterFactory

        router = RouterFactory(operator=op)
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))

        body = APIClient().get(
            f"/api/v1/pppoe/suspended-notice/?router={router.id}"
            f"&account={client.account_number}"
        ).json()

        assert body["paybill"] == "4123456"  # OURS, not the ISP's
        # The account number is the ONLY thing that routes the money to the right
        # ISP and the right subscriber.
        assert body["client"]["account_number"] == client.account_number
        assert "ACCOUNT NUMBER" in body["how_to_pay"]

    def test_account_lookup_shows_the_same_paybill(self, settings):
        settings.DARAJA_SHORTCODE = "4123456"
        op = OperatorFactory(slug="isp2")
        from .factories import RouterFactory

        router = RouterFactory(operator=op)
        client = PppoeClientFactory(operator=op, plan__price=Decimal("1500"))

        body = APIClient().get(
            f"/api/v1/pppoe/account-lookup/?router={router.id}"
            f"&account={client.account_number}"
        ).json()
        assert body["paybill"] == "4123456"
