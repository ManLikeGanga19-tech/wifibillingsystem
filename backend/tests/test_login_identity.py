"""Two identifiers, one account.

An ISP signs up with an email address and then never types a phone number again.
Making them remember which one the login box wanted is a self-inflicted support
ticket, so the box takes either — and a phone number in whatever shape they happen to
write it, because 0712…, +254712… and 712… are the same number to everyone except a
computer.

The constraint that makes this safe is that email is now UNIQUE, case-insensitively.
Two accounts sharing an address would make "sign in with your email" ambiguous, and
the payout-change code has to land in exactly one inbox.

What must NOT happen: the login box becoming an oracle that tells a stranger which
emails are registered. An unknown address and a wrong password fail identically.
"""

import pytest
from django.db.utils import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.auth_views import resolve_identifier
from apps.accounts.models import Role, User

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
PASSWORD = "sup3rsecret"


def make_owner(**kwargs):
    user = UserFactory(is_staff=True, role=Role.TENANT_OWNER, **kwargs)
    user.set_password(PASSWORD)
    user.save()
    return user


class TestSignInWithEitherIdentifier:
    def test_the_phone_still_works(self):
        user = make_owner()
        resp = APIClient().post(
            LOGIN, {"phone": user.phone, "password": PASSWORD}, format="json"
        )
        assert resp.status_code == 200

    def test_the_email_works_too(self):
        make_owner(email="ann@acme.co.ke")
        resp = APIClient().post(
            LOGIN, {"phone": "ann@acme.co.ke", "password": PASSWORD}, format="json"
        )
        assert resp.status_code == 200, resp.content

    def test_the_email_is_case_insensitive(self):
        """Nobody should fail to log in because of a capital letter."""
        make_owner(email="ann@acme.co.ke")
        resp = APIClient().post(
            LOGIN, {"phone": "Ann@Acme.CO.KE", "password": PASSWORD}, format="json"
        )
        assert resp.status_code == 200

    def test_an_email_sent_in_the_email_field_works(self):
        """Clients that do the obvious thing shouldn't be punished for it."""
        make_owner(email="ann@acme.co.ke")
        resp = APIClient().post(
            LOGIN, {"email": "ann@acme.co.ke", "password": PASSWORD}, format="json"
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize("written_as", ["0712345678", "+254712345678", "712345678"])
    def test_a_phone_number_in_any_shape_is_the_same_number(self, written_as):
        make_owner(phone="254712345678")
        resp = APIClient().post(
            LOGIN, {"phone": written_as, "password": PASSWORD}, format="json"
        )
        assert resp.status_code == 200, f"{written_as} should be accepted"

    def test_the_wrong_password_still_fails_on_either_identifier(self):
        make_owner(email="ann@acme.co.ke")
        for ident in ("ann@acme.co.ke", "254712000001"):
            assert (
                APIClient()
                .post(LOGIN, {"phone": ident, "password": "wrong"}, format="json")
                .status_code
                == 401
            )


class TestTheLoginBoxIsNotAnOracle:
    def test_an_unknown_email_fails_exactly_like_a_wrong_password(self):
        """If "no such account" looked different from "wrong password", the login box
        would happily tell a stranger which of our ISPs' emails are real."""
        make_owner(email="ann@acme.co.ke")

        unknown = APIClient().post(
            LOGIN, {"phone": "nobody@nowhere.com", "password": PASSWORD}, format="json"
        )
        wrong_pw = APIClient().post(
            LOGIN, {"phone": "ann@acme.co.ke", "password": "wrong"}, format="json"
        )

        assert unknown.status_code == wrong_pw.status_code == 401
        assert unknown.json() == wrong_pw.json()  # byte for byte

    def test_garbage_is_a_failed_login_not_a_server_error(self):
        """normalize_msisdn RAISES on nonsense. Unhandled, that is a 500 on the one
        endpoint every attacker pokes first."""
        resp = APIClient().post(LOGIN, {"phone": "!!!", "password": "x"}, format="json")
        assert resp.status_code == 401

    def test_no_identifier_at_all_is_a_failed_login(self):
        assert APIClient().post(LOGIN, {"password": "x"}, format="json").status_code == 401


class TestEmailIsUnique:
    def test_two_accounts_cannot_share_an_email(self):
        UserFactory(email="ann@acme.co.ke")
        with pytest.raises(IntegrityError):
            UserFactory(email="ann@acme.co.ke")

    def test_not_even_in_a_different_case(self):
        """Otherwise 'sign in with your email' has two answers."""
        UserFactory(email="ann@acme.co.ke")
        with pytest.raises(IntegrityError):
            UserFactory(email="ANN@ACME.CO.KE")

    def test_a_stored_email_is_canonicalised_to_lowercase(self):
        user = UserFactory(email="  Ann@Acme.CO.KE  ")
        user.refresh_from_db()
        assert user.email == "ann@acme.co.ke"

    def test_blank_emails_do_not_collide(self):
        """Platform and system accounts sign in by phone and have no email — the
        constraint must not treat them as duplicates of each other."""
        UserFactory(email="")
        UserFactory(email="")  # must not raise
        assert User.objects.filter(email="").count() == 2


class TestOneRoleOnTheIspSide:
    def test_the_tenant_sub_roles_are_gone(self):
        """They bought us nothing: a sub-role that cannot touch money, routers or
        plans can barely do anything, while every screen and permission check had to
        carry the branching anyway."""
        values = {value for value, _ in Role.choices}
        assert "tenant_manager" not in values
        assert "tenant_support" not in values
        assert values == {"platform_owner", "platform_support", "tenant_owner"}

    def test_an_isp_login_is_an_owner_and_may_move_its_own_money(self):
        owner = UserFactory(operator=OperatorFactory(), role=Role.TENANT_OWNER)
        assert owner.can_manage_money is True
        assert owner.is_read_only is False
        assert owner.is_platform_staff is False

    def test_read_only_now_means_platform_support_only(self):
        assert Role.read_only_roles() == {Role.PLATFORM_SUPPORT}


def test_resolve_identifier_never_leaks_whether_an_account_exists():
    """The unit behind it: an unknown email comes back as itself, so it fails at the
    password check like anything else — no early return, no distinct error."""
    UserFactory(phone="254712345678", email="ann@acme.co.ke")
    assert resolve_identifier("ann@acme.co.ke") == "254712345678"
    assert resolve_identifier("nobody@nowhere.com") == "nobody@nowhere.com"
    assert resolve_identifier("0712345678") == "254712345678"
    assert resolve_identifier("!!!") == "!!!"
