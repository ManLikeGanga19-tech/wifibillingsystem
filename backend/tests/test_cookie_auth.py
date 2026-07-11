"""Cookie auth + the self-healing acting tenant.

THE PRINCIPLE: no browser storage anywhere. The server owns the session, so there
is nothing in the client that can go stale after a deploy, and no user should ever
be told to "clear your cache".

The self-healing test is the important one: a stale or expired acting tenant used
to resolve to None, which 403'd every ISP endpoint and looked exactly like an API
outage. It must now fall back to the user's own ISP instead.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.cookie_auth import ACCESS_COOKIE, ACT_AS_COOKIE, REFRESH_COOKIE
from apps.accounts.models import Role
from apps.core.models import ImpersonationGrant

from .factories import OperatorFactory, PlanFactory, UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "sup3rsecret"


def make_user(**kwargs):
    user = UserFactory(**kwargs)
    user.set_password(PASSWORD)
    user.save()
    return user


class TestCookieLogin:
    def test_login_sets_httponly_cookies_and_leaks_no_token(self):
        user = make_user(is_staff=True, role=Role.TENANT_OWNER)
        c = APIClient()
        resp = c.post(
            "/api/v1/auth/login/", {"phone": user.phone, "password": PASSWORD}, format="json"
        )
        assert resp.status_code == 200, resp.content

        access = resp.cookies[ACCESS_COOKIE]
        refresh = resp.cookies[REFRESH_COOKIE]
        # httpOnly: JavaScript (and therefore XSS) cannot read these
        assert access["httponly"] is True
        assert refresh["httponly"] is True
        # The body must NOT carry a token — there is nothing for the app to store
        assert "access" not in resp.json()
        assert "refresh" not in resp.json()

    def test_the_cookie_alone_authenticates(self):
        user = make_user(is_staff=True, role=Role.TENANT_OWNER)
        PlanFactory(operator=user.operator, name="Cookie Plan")
        c = APIClient()
        c.post(
            "/api/v1/auth/login/", {"phone": user.phone, "password": PASSWORD}, format="json"
        )
        # No Authorization header anywhere — the browser just sends the cookie
        resp = c.get("/api/v1/me/")
        assert resp.status_code == 200
        assert resp.json()["phone"] == user.phone

    def test_bad_password_is_401(self):
        user = make_user(is_staff=True)
        c = APIClient()
        resp = c.post(
            "/api/v1/auth/login/", {"phone": user.phone, "password": "wrong"}, format="json"
        )
        assert resp.status_code == 401
        assert ACCESS_COOKIE not in resp.cookies

    def test_refresh_renews_the_access_cookie(self):
        user = make_user(is_staff=True)
        c = APIClient()
        c.post(
            "/api/v1/auth/login/", {"phone": user.phone, "password": PASSWORD}, format="json"
        )
        resp = c.post("/api/v1/auth/refresh/")
        assert resp.status_code == 200
        assert resp.cookies[ACCESS_COOKIE].value

    def test_refresh_without_a_session_is_401(self):
        assert APIClient().post("/api/v1/auth/refresh/").status_code == 401

    def test_logout_clears_every_cookie(self):
        user = make_user(is_staff=True)
        c = APIClient()
        c.post(
            "/api/v1/auth/login/", {"phone": user.phone, "password": PASSWORD}, format="json"
        )
        resp = c.post("/api/v1/auth/logout/")
        assert resp.status_code == 200
        # Cleared = set to empty. Nothing lingers for the next visitor.
        assert resp.cookies[ACCESS_COOKIE].value == ""
        assert resp.cookies[REFRESH_COOKIE].value == ""

    def test_bearer_tokens_still_work_for_scripts_and_tests(self):
        user = make_user(is_staff=True)
        c = APIClient()
        token = c.post(
            "/api/v1/auth/token/", {"phone": user.phone, "password": PASSWORD}, format="json"
        ).json()["access"]
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert c.get("/api/v1/me/").status_code == 200


class TestActingTenantIsServerState:
    """The acting tenant is set by the server when a grant opens, and cleared when
    it closes — it is never a value the frontend kept and could get out of sync."""

    def _platform(self):
        user = make_user(
            operator=OperatorFactory(slug="danamo-wisp"),
            is_staff=True,
            is_superuser=True,
            role=Role.PLATFORM_OWNER,
        )
        c = APIClient()
        c.post(
            "/api/v1/auth/login/", {"phone": user.phone, "password": PASSWORD}, format="json"
        )
        return c, user

    def test_starting_a_grant_sets_the_act_as_cookie(self):
        OperatorFactory(slug="acme")
        c, _ = self._platform()
        resp = c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "acme", "reason": "investigating a payment"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.cookies[ACT_AS_COOKIE].value == "acme"

    def test_ending_a_grant_clears_it(self):
        OperatorFactory(slug="acme")
        c, _ = self._platform()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "acme", "reason": "investigating a payment"},
            format="json",
        )
        resp = c.post("/api/v1/platform/impersonation/end/", {}, format="json")
        assert resp.cookies[ACT_AS_COOKIE].value == ""

    def test_the_cookie_alone_scopes_requests_to_that_tenant(self):
        acme = OperatorFactory(slug="acme")
        PlanFactory(operator=acme, name="Acme Plan")
        c, _ = self._platform()
        c.post(
            "/api/v1/platform/impersonation/start/",
            {"tenant": "acme", "reason": "investigating a payment"},
            format="json",
        )
        # The client now carries the server-set cookie; no header is sent.
        names = [p["name"] for p in c.get("/api/v1/plans/").json()["results"]]
        assert names == ["Acme Plan"]


class TestSelfHealingActingTenant:
    """The bug that kept coming back: a stale/expired acting tenant 403'd EVERY
    ISP endpoint, which looked like the API was down and could only be fixed by
    clearing browser storage. It must now degrade to the user's own ISP."""

    def _platform_with_own_isp(self):
        own = OperatorFactory(slug="danamo-wisp")
        PlanFactory(operator=own, name="Our Own Plan")
        user = make_user(
            operator=own, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        c = APIClient()
        c.force_authenticate(user=user)
        return c, user, own

    def test_expired_grant_falls_back_to_own_isp_instead_of_403(self):
        acme = OperatorFactory(slug="acme")
        c, user, _ = self._platform_with_own_isp()
        ImpersonationGrant.objects.create(
            actor=user,
            operator=acme,
            reason="expired session",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        c.credentials(HTTP_X_ACT_AS_TENANT="acme")

        resp = c.get("/api/v1/plans/")
        assert resp.status_code == 200  # NOT 403 — the console keeps working
        names = [p["name"] for p in resp.json()["results"]]
        assert names == ["Our Own Plan"]  # back in our own ISP, not acme's

    def test_unknown_slug_falls_back_to_own_isp(self):
        c, _, _ = self._platform_with_own_isp()
        c.credentials(HTTP_X_ACT_AS_TENANT="never-existed")
        resp = c.get("/api/v1/plans/")
        assert resp.status_code == 200
        assert [p["name"] for p in resp.json()["results"]] == ["Our Own Plan"]

    def test_fallback_never_leaks_the_other_tenants_data(self):
        """Degrading gracefully must not become degrading INSECURELY."""
        acme = OperatorFactory(slug="acme")
        PlanFactory(operator=acme, name="Acme Secret Plan")
        c, user, _ = self._platform_with_own_isp()
        ImpersonationGrant.objects.create(
            actor=user,
            operator=acme,
            reason="expired",
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        c.credentials(HTTP_X_ACT_AS_TENANT="acme")
        names = [p["name"] for p in c.get("/api/v1/plans/").json()["results"]]
        assert "Acme Secret Plan" not in names

    def test_platform_user_with_no_own_isp_still_fails_closed(self):
        """No own ISP to fall back to -> still 403, never an implicit 'all'."""
        OperatorFactory(slug="acme")
        user = make_user(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        c = APIClient()
        c.force_authenticate(user=user)
        c.credentials(HTTP_X_ACT_AS_TENANT="acme")
        assert c.get("/api/v1/pppoe/clients/").status_code == 403
