"""The 5-step ISP signup.

The happy path matters, but this is the ONLY anonymous write endpoint in the whole
system, so most of these tests are about the ways it could be abused:

  - email bombing a victim's inbox
  - brute-forcing a 6-digit code
  - using "send me a code" as an account-enumeration oracle
  - two people racing for the same slug/company name
  - a half-finished signup rotting in a browser (it can't — the server owns it)
"""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import Operator
from apps.signup.models import (
    MAX_CODE_ATTEMPTS,
    SignupApplication,
    SignupThrottle,
)

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

START = "/api/v1/signup/start/"
VERIFY = "/api/v1/signup/verify/"
RESEND = "/api/v1/signup/resend/"
STATE = "/api/v1/signup/state/"
AVAIL = "/api/v1/signup/availability/"
COMPANY = "/api/v1/signup/company/"
DETAILS = "/api/v1/signup/details/"
COMPLETE = "/api/v1/signup/complete/"


def code_from_email() -> str:
    """Pull the 6-digit code out of the email we just sent."""
    body = mail.outbox[-1].body
    return re.search(r"\b(\d{6})\b", body).group(1)


def start(c, email="jane@homelink.co.ke", name="Jane Doe"):
    return c.post(START, {"full_name": name, "email": email}, format="json")


def walk_to_step5(c, *, email="jane@homelink.co.ke", company="Homelink Networks",
                  slug="homelink", phone="0722111222"):
    """Drive the wizard up to (but not through) the final step."""
    start(c, email=email)
    c.post(VERIFY, {"code": code_from_email()}, format="json")
    c.post(COMPANY, {"company_name": company, "slug": slug}, format="json")
    c.post(
        DETAILS,
        {"county": "Nairobi", "phone": phone, "referral_source": "Google search"},
        format="json",
    )


class TestHappyPath:
    def test_five_steps_create_a_pending_isp(self):
        c = APIClient()
        walk_to_step5(c)

        resp = c.post(
            COMPLETE,
            {"password": "sup3rsecret", "confirm_password": "sup3rsecret", "accept_tos": True},
            format="json",
        )
        assert resp.status_code == 201, resp.content
        assert resp.json()["slug"] == "homelink"

        op = Operator.objects.get(slug="homelink")
        assert op.name == "Homelink Networks"
        assert op.county == "Nairobi"
        # PENDING, not active: they get the console but CANNOT take money until
        # their settlement account is verified.
        assert op.status == Operator.Status.PENDING

        owner = User.objects.get(operator=op)
        assert owner.phone == "254722111222"
        assert owner.email == "jane@homelink.co.ke"
        assert owner.is_staff
        assert owner.check_password("sup3rsecret")

    def test_tos_version_is_recorded(self):
        """An acceptance without a version is legally worthless."""
        c = APIClient()
        walk_to_step5(c)
        c.post(
            COMPLETE,
            {"password": "sup3rsecret", "confirm_password": "sup3rsecret", "accept_tos": True},
            format="json",
        )
        draft = SignupApplication.objects.get(email="jane@homelink.co.ke")
        assert draft.tos_version
        assert draft.tos_accepted_at

    def test_completing_twice_does_not_create_two_isps(self):
        c = APIClient()
        walk_to_step5(c)
        body = {"password": "sup3rsecret", "confirm_password": "sup3rsecret", "accept_tos": True}
        c.post(COMPLETE, body, format="json")
        c.post(COMPLETE, body, format="json")  # double-click / retry
        assert Operator.objects.filter(slug="homelink").count() == 1


class TestServerOwnsTheWizard:
    """No browser storage: the SERVER remembers which step you are on."""

    def test_state_resumes_after_a_refresh(self):
        c = APIClient()
        start(c)
        c.post(VERIFY, {"code": code_from_email()}, format="json")

        # "Refresh": the client keeps nothing — it just asks.
        state = c.get(STATE).json()
        assert state["step"] == SignupApplication.Step.COMPANY
        assert state["known"]["email"] == "jane@homelink.co.ke"
        assert state["known"]["email_verified"] is True

    def test_state_without_a_cookie_starts_at_step_1(self):
        state = APIClient().get(STATE).json()
        assert state["step"] == 1
        assert state["known"] == {}
        assert len(state["counties"]) == 47  # Kenya

    def test_state_never_leaks_the_code(self):
        c = APIClient()
        start(c)
        blob = str(c.get(STATE).json())
        assert code_from_email() not in blob
        assert "code_hash" not in blob


class TestEmailVerification:
    def test_a_wrong_code_is_rejected_and_counted(self):
        c = APIClient()
        start(c)
        resp = c.post(VERIFY, {"code": "000000"}, format="json")
        assert resp.status_code == 400
        draft = SignupApplication.objects.get(email="jane@homelink.co.ke")
        assert draft.attempts == 1
        assert draft.email_verified_at is None

    def test_the_code_cannot_be_brute_forced(self):
        """6 digits = 1,000,000 combinations. A bot with unlimited tries gets there;
        five attempts burns the draft."""
        c = APIClient()
        start(c)
        for _ in range(MAX_CODE_ATTEMPTS):
            c.post(VERIFY, {"code": "000000"}, format="json")

        # Even the RIGHT code no longer works — the draft is spent.
        resp = c.post(VERIFY, {"code": code_from_email()}, format="json")
        assert resp.status_code == 400
        assert "new one" in resp.json()["detail"].lower()

    def test_an_expired_code_is_rejected(self):
        c = APIClient()
        start(c)
        good = code_from_email()
        SignupApplication.objects.update(code_expires_at=timezone.now() - timedelta(minutes=1))
        assert c.post(VERIFY, {"code": good}, format="json").status_code == 400

    def test_the_code_is_burned_after_use(self):
        """A used code must not be replayable."""
        c = APIClient()
        start(c)
        c.post(VERIFY, {"code": code_from_email()}, format="json")
        draft = SignupApplication.objects.get(email="jane@homelink.co.ke")
        assert draft.code_hash == ""

    def test_the_code_is_never_stored_in_plaintext(self):
        c = APIClient()
        start(c)
        draft = SignupApplication.objects.get(email="jane@homelink.co.ke")
        assert code_from_email() not in draft.code_hash
        assert draft.code_hash  # it IS hashed, not blank

    def test_you_cannot_skip_verification(self):
        c = APIClient()
        start(c)
        resp = c.post(COMPANY, {"company_name": "Sneaky", "slug": "sneaky"}, format="json")
        assert resp.status_code == 400
        assert "verify" in resp.json()["detail"].lower()


class TestAntiEnumeration:
    """"Send me a code" must never reveal whether an email is registered."""

    def test_an_existing_email_gets_an_IDENTICAL_response(self):
        existing = UserFactory(email="taken@isp.co.ke")
        assert existing.email

        fresh = start(APIClient(), email="brand-new@isp.co.ke")
        taken = start(APIClient(), email="taken@isp.co.ke")

        assert fresh.status_code == taken.status_code == 201
        assert fresh.json()["detail"] == taken.json()["detail"]

    def test_an_existing_email_gets_a_SIGN_IN_nudge_not_a_code(self):
        """The caller learns nothing — but the real inbox owner is told the truth."""
        UserFactory(email="taken@isp.co.ke")
        mail.outbox.clear()
        start(APIClient(), email="taken@isp.co.ke")

        body = mail.outbox[-1].body
        assert "already have" in body.lower()
        assert not re.search(r"\b\d{6}\b", body)  # definitely NOT a code

    def test_an_existing_email_cannot_be_verified_into_an_account(self):
        UserFactory(email="taken@isp.co.ke")
        c = APIClient()
        start(c, email="taken@isp.co.ke")
        # No code was ever minted, so nothing can verify.
        for guess in ("000000", "123456", "999999"):
            assert c.post(VERIFY, {"code": guess}, format="json").status_code == 400


class TestAbuseControls:
    def test_we_cannot_be_used_to_bomb_an_inbox(self):
        """Rate-limited per TARGET, not just per endpoint — otherwise anyone could
        point us at a competitor's inbox."""
        victim = "victim@example.com"
        for _ in range(SignupThrottle.MAX_PER_EMAIL):
            assert start(APIClient(), email=victim).status_code == 201

        blocked = start(APIClient(), email=victim)
        assert blocked.status_code == 429

    def test_resend_has_a_cooldown(self):
        c = APIClient()
        start(c)
        resp = c.post(RESEND)
        assert resp.status_code == 429  # we JUST sent one
        assert "wait" in resp.json()["detail"].lower()

    def test_resend_works_after_the_cooldown(self):
        c = APIClient()
        start(c)
        SignupApplication.objects.update(last_sent_at=timezone.now() - timedelta(minutes=5))
        mail.outbox.clear()
        assert c.post(RESEND).status_code == 200
        assert re.search(r"\b\d{6}\b", mail.outbox[-1].body)  # a fresh code


class TestUniqueness:
    def test_a_taken_slug_is_reported_unavailable(self):
        OperatorFactory(slug="homelink", name="Homelink Networks")
        c = APIClient()
        start(c)
        c.post(VERIFY, {"code": code_from_email()}, format="json")

        body = c.get(f"{AVAIL}?slug=homelink").json()
        assert body["slug_available"] is False
        assert body["suggestion"]  # offer something they CAN have

    def test_a_taken_company_name_is_rejected_case_insensitively(self):
        OperatorFactory(slug="other", name="Homelink Networks")
        c = APIClient()
        start(c)
        c.post(VERIFY, {"code": code_from_email()}, format="json")

        resp = c.post(
            COMPANY, {"company_name": "homelink networks", "slug": "free-slug"}, format="json"
        )
        assert resp.status_code == 400
        assert "company name" in resp.json()["detail"].lower()

    def test_reserved_subdomains_cannot_be_claimed(self):
        c = APIClient()
        start(c)
        c.post(VERIFY, {"code": code_from_email()}, format="json")
        resp = c.post(COMPANY, {"company_name": "Admin Co", "slug": "admin"}, format="json")
        assert resp.status_code == 400

    def test_a_slug_held_by_another_live_draft_is_unavailable(self):
        """Two people racing for 'acme': the first to reach step 3 holds it."""
        first = APIClient()
        start(first, email="a@x.com")
        first.post(VERIFY, {"code": code_from_email()}, format="json")
        first.post(COMPANY, {"company_name": "Acme A", "slug": "acme"}, format="json")

        second = APIClient()
        start(second, email="b@x.com")
        second.post(VERIFY, {"code": code_from_email()}, format="json")
        resp = second.post(COMPANY, {"company_name": "Acme B", "slug": "acme"}, format="json")
        assert resp.status_code == 400

    def test_the_DATABASE_is_the_referee_not_the_draft(self):
        """Availability was checked at step 3, but someone else finished first. The
        unique constraint must catch it at step 5 rather than half-creating an ISP."""
        c = APIClient()
        walk_to_step5(c, slug="homelink", company="Homelink Networks")

        # Someone else takes the name between step 3 and step 5.
        OperatorFactory(slug="homelink", name="Homelink Networks")

        resp = c.post(
            COMPLETE,
            {"password": "sup3rsecret", "confirm_password": "sup3rsecret", "accept_tos": True},
            format="json",
        )
        assert resp.status_code == 400
        assert "taken" in resp.json()["detail"].lower()
        assert User.objects.filter(email="jane@homelink.co.ke").count() == 0  # nothing half-made

    def test_a_duplicate_phone_is_blocked_at_step_4(self):
        UserFactory(phone="254722111222")
        c = APIClient()
        start(c)
        c.post(VERIFY, {"code": code_from_email()}, format="json")
        c.post(COMPANY, {"company_name": "New ISP", "slug": "new-isp"}, format="json")
        resp = c.post(
            DETAILS, {"county": "Nairobi", "phone": "0722111222"}, format="json"
        )
        assert resp.status_code == 400


class TestStep5Validation:
    def test_passwords_must_match(self):
        c = APIClient()
        walk_to_step5(c)
        resp = c.post(
            COMPLETE,
            {"password": "sup3rsecret", "confirm_password": "different", "accept_tos": True},
            format="json",
        )
        assert resp.status_code == 400

    def test_tos_must_be_accepted(self):
        c = APIClient()
        walk_to_step5(c)
        resp = c.post(
            COMPLETE,
            {"password": "sup3rsecret", "confirm_password": "sup3rsecret", "accept_tos": False},
            format="json",
        )
        assert resp.status_code == 400
        assert Operator.objects.filter(slug="homelink").count() == 0


class TestExpiry:
    def test_an_expired_draft_cannot_be_used(self):
        c = APIClient()
        start(c)
        SignupApplication.objects.update(expires_at=timezone.now() - timedelta(hours=1))
        resp = c.post(VERIFY, {"code": "123456"}, format="json")
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_abandoned_drafts_are_swept(self):
        from apps.signup.services import sweep_expired

        start(APIClient())
        SignupApplication.objects.update(expires_at=timezone.now() - timedelta(hours=1))
        assert sweep_expired() == 1
        assert SignupApplication.objects.count() == 0

    def test_the_sweep_never_deletes_a_completed_signup(self):
        from apps.signup.services import sweep_expired

        c = APIClient()
        walk_to_step5(c)
        c.post(
            COMPLETE,
            {"password": "sup3rsecret", "confirm_password": "sup3rsecret", "accept_tos": True},
            format="json",
        )
        SignupApplication.objects.update(expires_at=timezone.now() - timedelta(hours=1))
        assert sweep_expired() == 0  # it made a real ISP; the record stays
        assert SignupApplication.objects.count() == 1
