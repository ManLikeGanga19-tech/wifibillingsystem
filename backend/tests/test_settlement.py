"""Settlement: plug-and-play in, confirmed on the way out.

Registering a payout account is INSTANT — we do not spend money proving accounts for
ISPs who may never trade a shilling. The paybill itself is the KYC bar (Safaricom
already vetted them to issue it), and we inherit that for free.

The first payout does the proving, and it costs us nothing: the ISP gets their full
money immediately, that payout carries a code, they read it back. Until they do, no
SECOND payout leaves.

What that really defends is ACCOUNT TAKEOVER — someone in an ISP's console swapping
the payout destination and draining the wallet. Verifying at signup would not have
touched it; the account is already verified before an attacker changes it. So
changing a confirmed account re-arms the cycle and warns the real owner.
"""

from decimal import Decimal

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry, Payout
from apps.billing.services import WalletError, request_payout
from apps.core.models import Operator
from apps.core.settlement import MAX_ATTEMPTS

from .factories import OperatorFactory, PppoeClientFactory, UserFactory

pytestmark = pytest.mark.django_db

SET = "/api/v1/operator/settlement/"
CONFIRM = "/api/v1/operator/settlement/confirm/"
WITHDRAW = "/api/v1/billing/payouts/withdraw/"

PAYBILL = {"method": "paybill", "settlement_paybill": "555777", "settlement_name": "Acme Ltd"}


def fresh_isp(**kw):
    """A brand-new signup: pending, nowhere to be paid yet."""
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


def fund(operator, amount="5000"):
    LedgerEntry.objects.create(
        operator=operator, entry_type=LedgerEntry.Type.SALE, amount=Decimal(amount)
    )


def pay_out(operator, user, amount="1000"):
    """Request a withdrawal and mark it paid, as the platform would."""
    from apps.billing.services import mark_payout_paid

    p = request_payout(
        operator=operator,
        amount=Decimal(amount),
        user=user,
        method="paybill",
        destination={"phone": "254712345678"},
    )
    return mark_payout_paid(p, by=user, mpesa_reference="REF123")


class TestPlugAndPlay:
    """No micro-transfer, no waiting, no cost to us for ISPs who never trade."""

    def test_adding_an_account_switches_payments_ON_immediately(self):
        op = fresh_isp()
        assert op.can_transact is False

        resp = owner_of(op).post(SET, PAYBILL, format="json")
        assert resp.status_code == 201, resp.content

        op.refresh_from_db()
        assert op.status == Operator.Status.ACTIVE  # live, no human, no transfer
        assert op.can_transact is True
        assert op.trial_ends_at is not None  # the free month starts now
        assert op.settlement_verified_at is None  # not yet CONFIRMED — that's fine

    def test_going_live_releases_money_held_while_they_set_up(self):
        op = fresh_isp()
        client = PppoeClientFactory(operator=op, plan__price=Decimal("2000"))
        from apps.payments.c2b import process_c2b_confirmation

        process_c2b_confirmation(
            {"TransID": "S1", "TransAmount": "2000",
             "BillRefNumber": client.account_number, "MSISDN": "254712345678"}
        )
        from apps.billing.services import wallet_balance

        assert wallet_balance(op) == Decimal("0.00")

        owner_of(op).post(SET, PAYBILL, format="json")
        assert wallet_balance(op) == Decimal("2000.00")  # nobody loses a shilling

    def test_a_bank_account_works_too(self):
        op = fresh_isp()
        resp = owner_of(op).post(
            SET,
            {"method": "bank", "payout_bank_name": "I&M Bank",
             "payout_bank_account_number": "0123456789",
             "payout_bank_account_name": "Acme Ltd"},
            format="json",
        )
        assert resp.status_code == 201
        op.refresh_from_db()
        assert op.can_transact is True

    def test_a_paybill_must_be_digits(self):
        op = fresh_isp()
        resp = owner_of(op).post(
            SET, {**PAYBILL, "settlement_paybill": "not-a-paybill"}, format="json"
        )
        assert resp.status_code == 400
        op.refresh_from_db()
        assert op.can_transact is False

    def test_only_the_OWNER_may_set_it(self):
        """Setting the destination IS withdrawing, one step removed."""
        op = fresh_isp()
        assert owner_of(op, role=Role.TENANT_SUPPORT).post(
            SET, PAYBILL, format="json"
        ).status_code == 403


class TestTheFirstPayoutProvesIt:
    def test_the_first_payout_is_paid_IN_FULL_and_carries_a_code(self):
        """They get all their money at once — we don't hold any of it back."""
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op, "5000")

        user = op.users.first()
        payout = pay_out(op, user, "1000")

        assert payout.amount == Decimal("1000.00")  # the FULL amount
        assert payout.confirmation_code.startswith("WOS-")
        assert payout.confirmed_at is None

    def test_a_SECOND_payout_is_blocked_until_they_confirm(self):
        """This is the cap: a wrong or hijacked destination costs ONE payout, not an
        open drain."""
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op, "5000")
        user = op.users.first()

        pay_out(op, user, "1000")

        with pytest.raises(WalletError, match="Confirm your last payout"):
            request_payout(
                operator=op, amount=Decimal("1000"), user=user,
                method="paybill", destination={"phone": "254712345678"},
            )

    def test_confirming_the_code_unlocks_payouts_permanently(self):
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op, "5000")
        user = op.users.first()
        payout = pay_out(op, user, "1000")

        resp = c.post(CONFIRM, {"code": payout.confirmation_code}, format="json")
        assert resp.status_code == 200, resp.content

        op.refresh_from_db()
        assert op.settlement_verified_at is not None
        payout.refresh_from_db()
        assert payout.confirmed_at is not None

        # ...and a second payout now goes straight through, with NO code attached.
        second = request_payout(
            operator=op, amount=Decimal("500"), user=user,
            method="paybill", destination={"phone": "254712345678"},
        )
        assert second.confirmation_code == ""

    def test_the_code_is_accepted_without_the_prefix(self):
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op)
        payout = pay_out(op, op.users.first())

        bare = payout.confirmation_code.removeprefix("WOS-")
        assert c.post(CONFIRM, {"code": bare.lower()}, format="json").status_code == 200

    def test_a_wrong_code_is_counted_and_capped(self):
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op)
        payout = pay_out(op, op.users.first())

        for _ in range(MAX_ATTEMPTS):
            assert c.post(CONFIRM, {"code": "WOS-ZZZZ"}, format="json").status_code == 400

        # Even the RIGHT code no longer works — they must talk to a human.
        resp = c.post(CONFIRM, {"code": payout.confirmation_code}, format="json")
        assert resp.status_code == 400
        assert "support" in resp.json()["detail"].lower()

    def test_there_is_nothing_to_confirm_before_a_payout(self):
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        resp = c.post(CONFIRM, {"code": "WOS-ABCD"}, format="json")
        assert resp.status_code == 400
        assert "nothing to confirm" in resp.json()["detail"].lower()

    def test_the_code_uses_an_unambiguous_alphabet(self):
        """They read this off an M-Pesa SMS and type it back. Every O/0 or I/1 is a
        support ticket."""
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op)
        code = pay_out(op, op.users.first()).confirmation_code.removeprefix("WOS-")
        assert not (set(code) & set("O0I1S5"))


class TestAccountTakeover:
    """The attack this actually defends: someone in an ISP's console swaps the payout
    destination to their own and drains the wallet."""

    def _confirmed_isp(self):
        op = fresh_isp()
        c = owner_of(op)
        c.post(SET, PAYBILL, format="json")
        op.refresh_from_db()
        fund(op, "50000")
        payout = pay_out(op, op.users.first())
        c.post(CONFIRM, {"code": payout.confirmation_code}, format="json")
        op.refresh_from_db()
        assert op.settlement_verified_at is not None
        return op, c

    def test_changing_a_CONFIRMED_account_re_arms_confirmation(self):
        """An attacker gets at most ONE payout to their new account — not a drain."""
        op, c = self._confirmed_isp()

        c.post(SET, {**PAYBILL, "settlement_paybill": "999888"}, format="json")
        op.refresh_from_db()
        assert op.settlement_verified_at is None  # must be proved again

        user = op.users.first()
        first = request_payout(
            operator=op, amount=Decimal("1000"), user=user,
            method="paybill", destination={"phone": "254712345678"},
        )
        assert first.confirmation_code  # carries a code again

        from apps.billing.services import mark_payout_paid

        mark_payout_paid(first, by=user, mpesa_reference="X")

        # ...and the drain stops here.
        with pytest.raises(WalletError, match="Confirm your last payout"):
            request_payout(
                operator=op, amount=Decimal("1000"), user=user,
                method="paybill", destination={"phone": "254712345678"},
            )

    def test_changing_a_confirmed_account_EMAILS_the_owner(self):
        """Reaches the real owner even if the attacker is the one in the console."""
        op, c = self._confirmed_isp()
        op.contact_email = "owner@acme.co.ke"
        op.save()
        mail.outbox.clear()

        c.post(SET, {**PAYBILL, "settlement_paybill": "999888"}, format="json")

        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert "999888" in body  # the NEW destination
        assert "555777" in body  # and what it replaced
        assert "did not do this" in body.lower()  # the warning

    def test_a_first_time_account_does_NOT_email_a_warning(self):
        """Only a CHANGE is suspicious. Don't cry wolf on every signup."""
        op = fresh_isp(contact_email="owner@acme.co.ke")
        mail.outbox.clear()
        owner_of(op).post(SET, PAYBILL, format="json")
        assert mail.outbox == []


class TestDefenceInDepth:
    def test_an_ACTIVE_isp_with_NO_account_still_cannot_transact(self):
        """If anyone ever flips status=active by hand — in the admin, or straight in
        the database — money still does not move for a business with nowhere to be
        paid."""
        op = OperatorFactory(
            status=Operator.Status.ACTIVE,
            settlement_method="",
            settlement_paybill="",
            settlement_verified_at=None,
        )
        assert op.status == Operator.Status.ACTIVE
        assert op.can_transact is False

    def test_the_platforms_own_isp_is_exempt(self):
        """Settling to ourselves is meaningless."""
        op = OperatorFactory(
            status=Operator.Status.ACTIVE,
            is_platform_owned=True,
            settlement_method="",
            settlement_paybill="",
        )
        assert op.can_transact is True


class TestTheSuspendedNoticeBug:
    """🔴 The page told a cut-off subscriber to pay the ISP'S OWN shortcode. C2B
    confirmations only ever arrive at DANAMO's paybill — so anyone who followed those
    instructions either paid the ISP directly (we never saw it, and they STAYED CUT
    OFF despite having paid) or was shown no paybill at all."""

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

        assert body["paybill"] == "4123456"  # OURS, never the ISP's
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


class TestPayoutDestination:
    def test_a_paybill_payout_names_the_paybill(self):
        p = Payout(method=Payout.Method.PAYBILL, paybill="555777", amount=Decimal("100"))
        assert p.destination == "Paybill 555777"
