"""Two-factor on the money paths.

WHY TOTP AND NOT AN EMAILED CODE. An emailed code proves someone can read an inbox —
so it is the right tool for verifying an address at signup, and the wrong tool for
guarding a payout. As a guard it inherits every weakness of email: it can be delayed,
it can land in spam, and it falls entirely to whoever owns the owner's Gmail.

An authenticator depends on nothing, works offline, and survives an email compromise.
So email keeps its real job — proving the address and NOTIFYING — and TOTP takes over
authorising the two things that move money: withdrawing, and changing where the money
goes.

Scope is deliberately narrow: money only. Losing a phone must cost an ISP their
payouts, not their whole console — they still have a network to run while they recover.
"""

from datetime import timedelta
from decimal import Decimal

import pyotp
import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import mfa
from apps.accounts.mfa import MfaDevice, MfaError, MfaRequired
from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.core.models import Operator

from .factories import OperatorFactory, UserFactory, enrol_mfa, mfa_code

pytestmark = pytest.mark.django_db

SETUP = "/api/v1/auth/mfa/setup/"
CONFIRM = "/api/v1/auth/mfa/confirm/"
STATUS = "/api/v1/auth/mfa/"
DISABLE = "/api/v1/auth/mfa/disable/"
RECOVERY = "/api/v1/auth/mfa/recovery-codes/"
WITHDRAW = "/api/v1/billing/payouts/withdraw/"
SETTLEMENT = "/api/v1/operator/settlement/"
RESET_MFA = "/api/v1/platform/reset-mfa/"

PAYBILL = {"method": "paybill", "settlement_paybill": "555777", "settlement_name": "Acme Ltd"}


def live_isp():
    """An ISP that has gone live and has money to withdraw."""
    op = OperatorFactory(
        status=Operator.Status.ACTIVE,
        settlement_method="paybill",
        settlement_paybill="555777",
        settlement_name="Acme Ltd",
    )
    owner = UserFactory(
        operator=op, is_staff=True, role=Role.TENANT_OWNER, email="owner@acme.co.ke"
    )
    LedgerEntry.objects.create(
        operator=op, entry_type=LedgerEntry.Type.SALE, amount=Decimal("50000")
    )
    c = APIClient()
    c.force_authenticate(user=owner)
    return op, owner, c


def enrol(user, client) -> str:
    """Walk the real enrolment flow and return the shared secret."""
    resp = client.post(SETUP, {}, format="json")
    secret = resp.json()["secret"]
    code = pyotp.TOTP(secret).now()
    client.post(CONFIRM, {"code": code}, format="json")
    return secret


def code_for(secret: str) -> str:
    return pyotp.TOTP(secret).now()


class TestEnrolment:
    def test_setup_returns_a_scannable_qr_and_a_typeable_secret(self):
        _, _, c = live_isp()
        body = c.post(SETUP, {}, format="json").json()
        assert body["qr"].startswith("data:image/png;base64,")  # rendered server-side
        assert body["secret"]
        assert "otpauth://totp/" in body["uri"]
        assert "WIFI.OS" in body["uri"]  # named in their app, not "Unknown"

    def test_an_unconfirmed_device_gates_NOTHING(self):
        """A botched enrolment must not lock them out with a secret they never
        successfully scanned."""
        _, owner, c = live_isp()
        c.post(SETUP, {}, format="json")  # started, never confirmed
        assert mfa.is_enrolled(owner) is False

    def test_confirming_needs_a_real_code_from_the_app(self):
        _, owner, c = live_isp()
        c.post(SETUP, {}, format="json")
        assert c.post(CONFIRM, {"code": "000000"}, format="json").status_code == 400
        assert mfa.is_enrolled(owner) is False

    def test_confirming_switches_it_on_and_issues_recovery_codes_ONCE(self):
        _, owner, c = live_isp()
        secret = c.post(SETUP, {}, format="json").json()["secret"]

        body = c.post(CONFIRM, {"code": code_for(secret)}, format="json").json()

        assert len(body["recovery_codes"]) == 10
        assert mfa.is_enrolled(owner) is True
        # They exist in readable form exactly once. The DB holds hashes.
        stored = MfaDevice.objects.get(user=owner).recovery_codes.values_list(
            "code_hash", flat=True
        )
        for plaintext in body["recovery_codes"]:
            assert plaintext not in stored

    def test_the_secret_is_encrypted_at_rest(self):
        """A leaked database dump must not hand out working second factors."""
        from django.db import connection

        _, owner, c = live_isp()
        secret = enrol(owner, c)

        with connection.cursor() as cur:
            cur.execute("SELECT secret FROM accounts_mfadevice WHERE user_id = %s", [owner.pk])
            raw = cur.fetchone()[0]
        assert secret not in raw  # ciphertext, not the seed


class TestWithdrawingNeedsTheSecondFactor:
    def test_an_ISP_with_no_authenticator_is_told_to_set_one_up(self):
        """We do not silently wave them through. This is the moment it matters, and
        any other moment they will not bother."""
        _, _, c = live_isp()
        resp = c.post(
            WITHDRAW, {"amount": "1000", "method": "mpesa", "phone": "0712345678"},
            format="json",
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["mfa_required"] is True
        assert body["enrolled"] is False  # so the UI shows ENROL, not a code box

    def test_a_withdrawal_without_a_code_is_refused(self):
        _, owner, c = live_isp()
        enrol(owner, c)
        resp = c.post(
            WITHDRAW, {"amount": "1000", "method": "mpesa", "phone": "0712345678"},
            format="json",
        )
        assert resp.status_code == 403
        assert resp.json()["mfa_required"] is True
        assert resp.json()["enrolled"] is True  # so the UI shows the code box

    def test_a_wrong_code_is_refused(self):
        _, owner, c = live_isp()
        enrol(owner, c)
        resp = c.post(
            WITHDRAW,
            {"amount": "1000", "method": "mpesa", "phone": "0712345678", "mfa_code": "000000"},
            format="json",
        )
        assert resp.status_code == 400

    def test_the_right_code_lets_the_money_out(self):
        _, owner, c = live_isp()
        secret = enrol(owner, c)
        resp = c.post(
            WITHDRAW,
            {
                "amount": "1000", "method": "mpesa", "phone": "0712345678",
                "mfa_code": code_for(secret),
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content

    def test_a_code_cannot_be_used_TWICE(self):
        """A TOTP code stays valid for its whole 30-second window. Without a replay
        guard the same six digits authorise two withdrawals — a double-click, a
        shoulder-surfer, a code scraped from a log."""
        _, owner, c = live_isp()
        secret = enrol(owner, c)
        code = code_for(secret)

        first = c.post(
            WITHDRAW,
            {"amount": "1000", "method": "mpesa", "phone": "0712345678", "mfa_code": code},
            format="json",
        )
        assert first.status_code == 201

        # Confirm the first payout so the one-payout cap isn't what stops us here —
        # we are testing the REPLAY guard, not that cap.
        from apps.billing.models import Payout
        from apps.billing.services import mark_payout_paid

        payout = Payout.objects.get(pk=first.json()["id"])
        mark_payout_paid(payout, by=owner, mpesa_reference="X")
        c.post(
            "/api/v1/operator/settlement/confirm/",
            {"code": payout.confirmation_code},
            format="json",
        )

        second = c.post(
            WITHDRAW,
            {"amount": "500", "method": "mpesa", "phone": "0712345678", "mfa_code": code},
            format="json",
        )
        assert second.status_code == 400
        assert "already been used" in second.json()["detail"].lower()


class TestChangingThePayoutAccount:
    def test_TOTP_replaces_the_emailed_code_once_enrolled(self):
        """Offering both would make the change only as strong as the weaker one, and
        the authenticator would be decoration."""
        op, owner, c = live_isp()
        secret = enrol(owner, c)
        mail.outbox.clear()

        # No code -> demanded, and NOT emailed one.
        resp = c.post(SETTLEMENT, {**PAYBILL, "settlement_paybill": "999888"}, format="json")
        assert resp.status_code == 403
        assert resp.json()["mfa_required"] is True
        assert mail.outbox == []  # no email code was sent
        op.refresh_from_db()
        assert op.settlement_paybill == "555777"  # untouched

        # With the code -> it lands.
        resp = c.post(
            SETTLEMENT,
            {**PAYBILL, "settlement_paybill": "999888", "code": code_for(secret)},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        op.refresh_from_db()
        assert op.settlement_paybill == "999888"

    def test_the_owner_is_STILL_emailed_a_tripwire(self):
        """Being asked and being told are different things. Even though TOTP authorised
        it, if that phone is in the wrong hands the email is how the owner finds out."""
        op, owner, c = live_isp()
        secret = enrol(owner, c)
        # Confirm the account so the change counts as a destination change.
        op.settlement_verified_at = op.created_at
        op.save()
        mail.outbox.clear()

        c.post(
            SETTLEMENT,
            {**PAYBILL, "settlement_paybill": "999888", "code": code_for(secret)},
            format="json",
        )

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["owner@acme.co.ke"]
        assert "999888" in mail.outbox[0].body

    def test_an_ISP_without_an_authenticator_still_gets_the_emailed_code(self):
        """The email path is the FALLBACK, not the norm — but it must keep working, or
        an ISP who never enrolled is locked out of their own settings."""
        op, _, c = live_isp()
        mail.outbox.clear()

        resp = c.post(SETTLEMENT, {**PAYBILL, "settlement_paybill": "999888"}, format="json")
        assert resp.status_code == 400
        assert resp.json()["code_required"] is True
        assert len(mail.outbox) == 1  # the emailed code


class TestRecovery:
    def test_a_recovery_code_works_when_the_phone_is_gone(self):
        """The worst thing this system could do is lock an ISP out of their own money."""
        _, owner, c = live_isp()
        c.post(SETUP, {}, format="json")
        secret = MfaDevice.objects.get(user=owner).secret
        codes = c.post(CONFIRM, {"code": pyotp.TOTP(secret).now()}, format="json").json()[
            "recovery_codes"
        ]

        resp = c.post(
            WITHDRAW,
            {
                "amount": "1000", "method": "mpesa", "phone": "0712345678",
                "mfa_code": codes[0],
            },
            format="json",
        )
        assert resp.status_code == 201

    def test_a_recovery_code_is_SINGLE_use(self):
        _, owner, c = live_isp()
        secret = enrol(owner, c)
        codes = mfa.regenerate_recovery_codes(owner, code_for(secret))

        mfa.verify(owner, codes[0])  # burned
        with pytest.raises(MfaError):
            mfa.verify(owner, codes[0])

    def test_using_a_recovery_code_WARNS_the_owner(self):
        """It means a lost phone or an intruder. Only the owner knows which, so only
        the owner can raise the alarm — but first they have to be told."""
        _, owner, c = live_isp()
        secret = enrol(owner, c)
        codes = mfa.regenerate_recovery_codes(owner, code_for(secret))
        mail.outbox.clear()

        mfa.verify(owner, codes[0])

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["owner@acme.co.ke"]
        assert "recovery code" in mail.outbox[0].subject.lower()
        assert "9 left" in mail.outbox[0].body  # 10 issued, 1 spent


class TestTurningItOff:
    def test_disabling_needs_a_current_code(self):
        """An attacker who could simply switch MFA off would not need to defeat it."""
        _, owner, c = live_isp()
        enrol(owner, c)

        assert c.post(DISABLE, {"code": "000000"}, format="json").status_code == 400
        assert mfa.is_enrolled(owner) is True

    def test_disabling_with_a_real_code_removes_it(self):
        _, owner, c = live_isp()
        secret = enrol(owner, c)
        assert c.post(DISABLE, {"code": code_for(secret)}, format="json").status_code == 200
        owner.refresh_from_db()
        assert mfa.is_enrolled(owner) is False


class TestScope:
    def test_login_does_NOT_require_a_code(self):
        """Money only. An ISP who loses their phone must still be able to see their
        clients and run their network while they recover."""
        _, owner, _ = live_isp()
        owner.set_password("sup3rsecret")
        owner.save()
        enrol(owner, APIClient_for(owner))

        resp = APIClient().post(
            "/api/v1/auth/login/",
            {"phone": owner.phone, "password": "sup3rsecret"},
            format="json",
        )
        assert resp.status_code == 200

    def test_reading_the_console_does_NOT_require_a_code(self):
        _, owner, c = live_isp()
        enrol(owner, c)
        assert c.get("/api/v1/billing/wallet/").status_code == 200
        assert c.get("/api/v1/plans/").status_code == 200


def APIClient_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_require_demands_enrolment_rather_than_waving_them_through():
    """The unit behind the gate: no authenticator is not a free pass."""
    op = OperatorFactory(status=Operator.Status.ACTIVE)
    owner = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
    with pytest.raises(MfaRequired):
        mfa.require(owner, "")


class TestTheLostPhone:
    """The last door out of a locked wallet — and, handled carelessly, a master key to
    every ISP's money."""

    def _platform_owner(self):
        user = UserFactory(
            operator=None, is_staff=True, role=Role.PLATFORM_OWNER, email="daniel@danamo.co.ke"
        )
        c = APIClient()
        c.force_authenticate(user=user)
        return user, c

    def test_the_platform_owner_can_clear_a_lost_authenticator(self):
        _, owner, oc = live_isp()
        enrol(owner, oc)
        _, pc = self._platform_owner()

        resp = pc.post(
            RESET_MFA, {"user_id": owner.pk, "reason": "Lost phone, ID verified by call"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert mfa.is_enrolled(owner) is False  # they can enrol a new phone

    def test_a_reason_is_MANDATORY(self):
        """"Who turned this off, and why" must be answerable months later, in front of
        an ISP who lost money."""
        _, owner, oc = live_isp()
        enrol(owner, oc)
        _, pc = self._platform_owner()
        resp = pc.post(RESET_MFA, {"user_id": owner.pk, "reason": ""}, format="json")
        assert resp.status_code == 400

    def test_read_only_platform_SUPPORT_cannot_do_it(self):
        """Support staff must not be able to switch off somebody's second factor."""
        _, owner, oc = live_isp()
        enrol(owner, oc)
        support = UserFactory(operator=None, is_staff=True, role=Role.PLATFORM_SUPPORT)
        c = APIClient()
        c.force_authenticate(user=support)

        resp = c.post(RESET_MFA, {"user_id": owner.pk, "reason": "lost phone"}, format="json")
        assert resp.status_code == 403
        assert mfa.is_enrolled(owner) is True

    def test_the_ISP_owner_is_EMAILED(self):
        """If they did not ask for this, that mail is the alarm."""
        _, owner, oc = live_isp()
        enrol(owner, oc)
        _, pc = self._platform_owner()
        mail.outbox.clear()

        pc.post(RESET_MFA, {"user_id": owner.pk, "reason": "lost phone"}, format="json")

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["owner@acme.co.ke"]
        body = mail.outbox[0].body
        assert "did not ask for this" in body.lower()
        assert "lost phone" in body  # the reason we were given, in their hands

    def test_withdrawals_FREEZE_for_24h_after_a_reset(self):
        """A reset is the one moment the second factor is down — exactly when a
        fraudulent reset would be cashed in. The freeze buys the real owner time to
        read the email and shout."""
        _, owner, oc = live_isp()
        enrol(owner, oc)
        _, pc = self._platform_owner()
        pc.post(RESET_MFA, {"user_id": owner.pk, "reason": "lost phone"}, format="json")

        # They enrol a new phone straight away...
        owner.refresh_from_db()
        oc.force_authenticate(user=owner)
        secret = enrol(owner, oc)

        # ...and the money still waits.
        resp = oc.post(
            WITHDRAW,
            {
                "amount": "1000", "method": "mpesa", "phone": "0712345678",
                "mfa_code": code_for(secret),
            },
            format="json",
        )
        assert resp.status_code == 403
        assert "paused" in resp.json()["detail"].lower()

    def test_the_freeze_lifts(self):
        from datetime import timedelta

        from django.utils import timezone

        _, owner, oc = live_isp()
        _, pc = self._platform_owner()
        pc.post(RESET_MFA, {"user_id": owner.pk, "reason": "lost phone"}, format="json")

        owner.refresh_from_db()
        owner.mfa_reset_at = timezone.now() - timedelta(hours=25)
        owner.save()
        oc.force_authenticate(user=owner)
        secret = enrol(owner, oc)

        resp = oc.post(
            WITHDRAW,
            {
                "amount": "1000", "method": "mpesa", "phone": "0712345678",
                "mfa_code": code_for(secret),
            },
            format="json",
        )
        assert resp.status_code == 201, resp.content


class TestMoneyCannotMoveOnABorrowedIdentity:
    """THE HOLE THE RESET FEATURE WOULD OTHERWISE OPEN.

    Without this, platform staff (or anyone who steals a platform account) open an
    impersonation grant, enrol their OWN authenticator, and withdraw an ISP's balance —
    the second factor satisfied by the attacker's own phone. The MFA reset would then be
    a master key to every wallet on the platform.

    Impersonation exists to TROUBLESHOOT. Troubleshooting never requires moving money.
    """

    def _impersonating(self, op):
        from apps.core.models import ImpersonationGrant

        actor = UserFactory(operator=None, is_staff=True, role=Role.PLATFORM_OWNER)
        ImpersonationGrant.objects.create(
            actor=actor,
            operator=op,
            reason="debugging a payment",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        c = APIClient()
        c.force_authenticate(user=actor)
        c.credentials(HTTP_X_ACT_AS_TENANT=op.slug)
        return actor, c

    def test_an_impersonator_cannot_withdraw(self):
        op, _, _ = live_isp()
        actor, c = self._impersonating(op)
        secret = enrol_mfa(actor)  # their OWN authenticator — must not help them

        resp = c.post(
            WITHDRAW,
            {
                "amount": "1000", "method": "mpesa", "phone": "0712345678",
                "mfa_code": mfa_code(secret),
            },
            format="json",
        )
        assert resp.status_code == 403
        assert "borrowed identity" in resp.json()["detail"].lower()

    def test_an_impersonator_cannot_change_where_the_money_goes(self):
        op, _, _ = live_isp()
        _, c = self._impersonating(op)

        resp = c.post(SETTLEMENT, {**PAYBILL, "settlement_paybill": "999888"}, format="json")
        assert resp.status_code == 403
        op.refresh_from_db()
        assert op.settlement_paybill == "555777"

    def test_an_impersonator_can_still_LOOK(self):
        """The feature still has to work — support must be able to see the wallet they
        are being asked about."""
        op, _, _ = live_isp()
        _, c = self._impersonating(op)
        assert c.get("/api/v1/billing/wallet/").status_code == 200
