"""The PUBLIC API surface, and the CSRF posture that cookie auth forces on us.

Two real bugs are pinned here. Both came from public views that set
`permission_classes = [AllowAny]` but left AUTHENTICATION switched on:

1. A staff cookie reached the captive portal (cookies ignore the port), DRF
   authenticated it, enforced CSRF, and a customer buying WiFi got
   "CSRF Failed: Origin checking failed" instead of an M-Pesa prompt.

2. Worse: `PlanViewSet` branched on `is_staff`, so that same stray cookie made the
   portal resolve the tenant from the STAFF's acting tenant instead of the router
   the customer is standing in front of — showing (and selling) the WRONG ISP's
   plans.
"""

from decimal import Decimal

import pytest
from django.test import Client as DjangoClient
from rest_framework.test import APIClient

from apps.accounts.cookie_auth import ACCESS_COOKIE
from apps.accounts.models import Role
from apps.plans.models import Plan

from .factories import OperatorFactory, PlanFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "sup3rsecret"


def signed_in_browser(user, enforce_csrf=False):
    """A real browser session: cookies, no Authorization header.

    NOTE: Django's test client sets `_dont_enforce_csrf_checks`, which silently
    skips CSRF. To actually exercise the protection we must opt in with
    `enforce_csrf_checks=True` — otherwise the test would pass no matter what.
    """
    user.set_password(PASSWORD)
    user.save()
    c = APIClient(enforce_csrf_checks=enforce_csrf)
    resp = c.post(
        "/api/v1/auth/login/", {"phone": user.phone, "password": PASSWORD}, format="json"
    )
    assert resp.status_code == 200
    return c, resp.json()["csrf_token"]


# A valid hotspot plan payload (duration is a DurationField).
def plan_payload(name):
    return {
        "name": name,
        "price": "10.00",
        "duration": "01:00:00",
        "download_kbps": 1024,
        "upload_kbps": 512,
    }


class TestPortalIsAnonymous:
    """A WiFi customer is never a logged-in staff user."""

    def test_stk_push_works_even_when_a_staff_cookie_is_present(self, monkeypatch):
        """THE BUG DANIEL HIT. The console's cookie leaks to the portal (same host,
        different port). The portal must ignore it entirely, not 403 the customer.

        Daraja is stubbed out. This test is about AUTH, and letting it reach the real
        Safaricom sandbox made it the one test in the suite that could fail because a
        network blipped — a red build that says nothing about our code is worse than no
        test at all.
        """
        from apps.payments.daraja import DarajaClient, DarajaError

        def no_network(*args, **kwargs):
            raise DarajaError("stubbed — no network in tests")

        monkeypatch.setattr(DarajaClient, "stk_push", no_network)

        op = OperatorFactory()
        router = RouterFactory(operator=op)
        plan = PlanFactory(operator=op, price=20)
        staff = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        c, _csrf = signed_in_browser(staff)

        # The customer's browser carries the staff cookie but sends NO csrf token —
        # exactly the situation that produced "CSRF Failed".
        resp = c.post(
            "/api/v1/payments/stk-push/",
            {"phone": "254797233957", "plan_id": plan.id, "router_id": router.id},
            format="json",
        )
        # It must NOT be a CSRF/permission failure. (502 is fine — no real Daraja
        # in tests; what matters is that we got PAST auth and into the handler.)
        assert resp.status_code != 403, resp.content
        assert ACCESS_COOKIE in c.cookies  # the cookie really was there

    def test_portal_plans_follow_the_ROUTER_not_the_staff_cookie(self):
        """THE QUIETER BUG. Two ISPs. A platform admin is acting as ISP A. A customer
        is standing in front of ISP B's router. They must see B's plans — never A's."""
        isp_a = OperatorFactory(slug="isp-a")
        isp_b = OperatorFactory(slug="isp-b")
        PlanFactory(operator=isp_a, name="A Plan", plan_type=Plan.PlanType.HOTSPOT)
        PlanFactory(operator=isp_b, name="B Plan", plan_type=Plan.PlanType.HOTSPOT)
        router_b = RouterFactory(operator=isp_b)

        admin = UserFactory(
            operator=isp_a, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
        c, _ = signed_in_browser(admin)

        names = [
            p["name"] for p in c.get(f"/api/v1/plans/?router={router_b.id}").json()["results"]
        ]
        assert names == ["B Plan"], names  # the router's owner decides
        assert "A Plan" not in names  # the cookie must not leak the wrong ISP in

    def test_portal_fails_closed_with_an_unknown_router(self):
        OperatorFactory()
        PlanFactory(name="Secret Plan")
        assert APIClient().get("/api/v1/plans/?router=99999").json()["results"] == []

    def test_voucher_redeem_is_anonymous(self):
        resp = APIClient().post(
            "/api/v1/vouchers/redeem/", {"code": "NOPE"}, format="json"
        )
        assert resp.status_code != 403  # reachable; the code itself is just invalid

    def test_suspended_notice_is_anonymous(self):
        op = OperatorFactory(slug="isp")
        router = RouterFactory(operator=op)
        resp = APIClient().get(f"/api/v1/pppoe/suspended-notice/?router={router.id}")
        assert resp.status_code == 200


class TestCsrfOnCookieAuth:
    """Moving the token into a cookie REINTRODUCES CSRF. A Bearer token could never
    be forged by another site; a cookie is attached automatically. So a
    cookie-authenticated WRITE must also echo the CSRF token."""

    def test_cookie_write_without_the_csrf_token_is_rejected(self):
        op = OperatorFactory()
        owner = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        c, _csrf = signed_in_browser(owner, enforce_csrf=True)

        # A forged cross-site request looks exactly like this: the browser attaches
        # our cookie, but the attacker cannot READ it, so cannot set the header.
        resp = c.post("/api/v1/plans/", plan_payload("Forged"), format="json")
        assert resp.status_code == 403, resp.content
        assert "CSRF" in str(resp.content)
        assert not Plan.objects.filter(name="Forged").exists()  # nothing was written

    def test_cookie_write_WITH_the_csrf_token_succeeds(self):
        op = OperatorFactory()
        owner = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        c, csrf = signed_in_browser(owner, enforce_csrf=True)

        resp = c.post(
            "/api/v1/plans/", plan_payload("Legit"), format="json", HTTP_X_CSRFTOKEN=csrf
        )
        assert resp.status_code == 201, resp.content
        assert Plan.objects.filter(name="Legit", operator=op).exists()

    def test_cookie_READS_never_need_a_csrf_token(self):
        op = OperatorFactory()
        owner = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        c, _ = signed_in_browser(owner, enforce_csrf=True)
        assert c.get("/api/v1/plans/").status_code == 200

    def test_bearer_tokens_are_exempt(self):
        """Scripts, tests and the CLI use a header — never vulnerable to CSRF, and
        must keep working without one."""
        op = OperatorFactory()
        owner = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        owner.set_password(PASSWORD)
        owner.save()
        c = APIClient(enforce_csrf_checks=True)
        token = c.post(
            "/api/v1/auth/token/", {"phone": owner.phone, "password": PASSWORD}, format="json"
        ).json()["access"]
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        resp = c.post("/api/v1/plans/", plan_payload("Scripted"), format="json")
        assert resp.status_code == 201, resp.content


class TestRouterEnrollStillWorks:
    """The setup script phones home from the ROUTER, not a browser. It must never be
    caught by browser-shaped protections."""

    def test_enroll_endpoint_is_reachable_without_auth_or_csrf(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        resp = DjangoClient().post(
            "/api/v1/routers/enroll/",
            data='{"token": "wrong-token", "password": "x"}',
            content_type="application/json",
        )
        # Reachable (its own token auth rejects it) — NOT a CSRF/auth wall.
        assert resp.status_code in (400, 401, 403, 404)
        assert "CSRF" not in resp.content.decode()
        assert router.operator == op  # sanity


class TestHotspotPricingUnchanged:
    """Guard the money path: a portal customer sees only ACTIVE HOTSPOT plans of the
    router's owner, at the right price."""

    def test_only_active_hotspot_plans_of_that_router(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        PlanFactory(operator=op, name="Live", price=Decimal("20"), is_active=True)
        PlanFactory(operator=op, name="Retired", price=Decimal("20"), is_active=False)

        results = APIClient().get(f"/api/v1/plans/?router={router.id}").json()["results"]
        names = [p["name"] for p in results]
        assert names == ["Live"]
