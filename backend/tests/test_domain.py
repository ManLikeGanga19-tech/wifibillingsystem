"""Settings > Domain: an ISP's address, and what it takes to change it safely.

Renaming a slug is the most disruptive thing an ISP can do to themselves. It moves the
subdomain their customers land on AND invalidates the redirect baked into every router.
The tests that matter are the ones about NOT breaking people:

  * the old address keeps working while routers catch up;
  * a name in its grace window cannot be handed to somebody else;
  * a router that did not get the memo is REPORTED, not glossed over.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core import domains
from apps.core.models import Operator
from apps.core.tenancy import _operator_for_slug
from apps.provisioning.adapters.base import ProvisioningError
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Router
from apps.provisioning.portal_sync import push_portal_to_router, refresh_portal

from .factories import OperatorFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db

DOMAIN = "/api/v1/operator/domain/"
CHECK = "/api/v1/operator/domain/check/"
CHANGE = "/api/v1/operator/domain/change/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def support(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.PLATFORM_SUPPORT)
    )
    return c


# --- what makes a legal address ----------------------------------------------------------


class TestSlugRules:
    @pytest.mark.parametrize("bad", ["ab", "-acme", "acme-", "AC ME", "ac--me", "a" * 31, ""])
    def test_illegal_names_are_refused(self, bad):
        """It becomes a DNS label, so it has to be one."""
        with pytest.raises(domains.DomainError):
            domains.validate(bad)

    def test_a_reserved_name_is_refused(self):
        with pytest.raises(domains.DomainError, match="reserved"):
            domains.validate("api")

    def test_a_good_name_is_normalised(self):
        assert domains.validate("  ACME-WiFi ") == "acme-wifi"


# --- the grace window: the thing that stops a rename being an outage ----------------------


class TestTheOldAddressKeepsWorking:
    def test_the_previous_subdomain_still_resolves_after_a_change(self):
        """A router that has not re-synced is still sending customers to the old name. If
        that name stopped resolving the moment the ISP hit save, every one of those
        customers would hit a dead page."""
        operator = OperatorFactory(slug="oldname")
        operator.previous_slug = "oldname"
        operator.slug = "newname"
        operator.slug_changed_at = timezone.now()
        operator.save()

        assert _operator_for_slug("newname") == operator
        assert _operator_for_slug("oldname") == operator  # still lands

    def test_the_old_subdomain_stops_resolving_once_the_grace_window_closes(self):
        """Otherwise a name could never be reused, and we would leak an ISP's old identity
        forever."""
        operator = OperatorFactory(slug="newname")
        operator.previous_slug = "oldname"
        operator.slug_changed_at = timezone.now() - timezone.timedelta(
            days=domains.GRACE_DAYS + 1
        )
        operator.save()

        assert _operator_for_slug("oldname") is None

    def test_a_name_inside_someone_elses_grace_window_cannot_be_taken(self):
        """The dangerous one. If we handed this name to a new ISP, the FIRST ISP's
        still-redirecting customers would land in a stranger's captive portal and pay a
        stranger."""
        mover = OperatorFactory(slug="newname")
        mover.previous_slug = "acme"
        mover.slug_changed_at = timezone.now()
        mover.save()

        available, reason = domains.is_available("acme")

        assert available is False
        assert "taken" in reason

    def test_that_name_frees_up_once_the_window_closes(self):
        mover = OperatorFactory(slug="newname")
        mover.previous_slug = "acme"
        mover.slug_changed_at = timezone.now() - timezone.timedelta(days=domains.GRACE_DAYS + 1)
        mover.save()

        available, _ = domains.is_available("acme")

        assert available is True


# --- the API ------------------------------------------------------------------------------


class TestTheDomainPage:
    def test_it_shows_the_isps_address(self, settings):
        settings.TENANT_BASE_DOMAIN = "wifios.co.ke"
        operator = OperatorFactory(slug="acme")

        body = owner(operator).get(DOMAIN).json()

        assert body["slug"] == "acme"
        assert body["domain"] == "acme.wifios.co.ke"
        assert body["url"] == "https://acme.wifios.co.ke"

    def test_checking_your_own_name_says_already_active(self):
        operator = OperatorFactory(slug="acme")

        body = owner(operator).get(CHECK, {"slug": "acme"}).json()

        assert body["available"] is True
        assert body["current"] is True

    def test_checking_a_taken_name_never_reveals_who_holds_it(self):
        """An availability check must not let anyone enumerate our customer list."""
        OperatorFactory(slug="rival", name="Rival Networks")
        operator = OperatorFactory(slug="acme")

        resp = owner(operator).get(CHECK, {"slug": "rival"})

        assert resp.json()["available"] is False
        assert "Rival" not in resp.content.decode()

    def test_a_bad_name_is_explained_not_just_rejected(self):
        operator = OperatorFactory(slug="acme")

        body = owner(operator).get(CHECK, {"slug": "ab"}).json()

        assert body["available"] is False
        assert "3 characters" in body["reason"]


class TestChangingIt:
    def test_the_move_repoints_the_isps_routers(self, settings):
        settings.PORTAL_BASE_URL = ""  # production shape: the real subdomain
        settings.TENANT_BASE_DOMAIN = "wifios.co.ke"
        operator = OperatorFactory(slug="acme")
        RouterFactory(operator=operator, provisioning_backend=Router.Backend.DUMMY)

        resp = owner(operator).post(CHANGE, {"slug": "acme-wifi"}, format="json")

        assert resp.status_code == 200
        operator.refresh_from_db()
        assert operator.slug == "acme-wifi"
        assert operator.previous_slug == "acme"
        # The router was actually told, with the NEW address.
        assert ("push_portal", "https://acme-wifi.wifios.co.ke") in DummyAdapter.calls

    def test_taking_a_rivals_name_is_refused(self):
        OperatorFactory(slug="rival")
        operator = OperatorFactory(slug="acme")

        resp = owner(operator).post(CHANGE, {"slug": "rival"}, format="json")

        assert resp.status_code == 400
        operator.refresh_from_db()
        assert operator.slug == "acme"  # unmoved

    def test_a_reserved_name_is_refused(self):
        operator = OperatorFactory(slug="acme")

        resp = owner(operator).post(CHANGE, {"slug": "admin"}, format="json")

        assert resp.status_code == 400
        operator.refresh_from_db()
        assert operator.slug == "acme"

    def test_moving_to_your_own_name_is_a_no_op_not_a_pointless_router_refresh(self):
        operator = OperatorFactory(slug="acme")

        resp = owner(operator).post(CHANGE, {"slug": "acme"}, format="json")

        assert resp.status_code == 400
        assert not DummyAdapter.calls

    def test_read_only_support_cannot_move_an_isp(self):
        operator = OperatorFactory(slug="acme")

        resp = support(operator).post(CHANGE, {"slug": "hijack"}, format="json")

        assert resp.status_code == 403
        operator.refresh_from_db()
        assert operator.slug == "acme"


# --- telling the truth about routers -------------------------------------------------------


class TestRouterSyncIsReportedHonestly:
    def test_a_synced_router_is_marked_as_on_the_current_domain(self, settings):
        settings.PORTAL_BASE_URL = ""
        settings.TENANT_BASE_DOMAIN = "wifios.co.ke"
        operator = OperatorFactory(slug="acme")
        router = RouterFactory(operator=operator, provisioning_backend=Router.Backend.DUMMY)

        push_portal_to_router(router.pk, domains.portal_url_for(operator))

        body = owner(operator).get(DOMAIN).json()
        assert body["routers"][0]["on_current_domain"] is True

    def test_a_router_that_refused_the_push_is_shown_as_NOT_on_the_new_domain(self, settings):
        """The one that matters. An offline router is still redirecting customers to the
        old address — reporting a clean success would let the ISP find that out from an
        angry customer instead of from us."""
        settings.PORTAL_BASE_URL = ""
        settings.TENANT_BASE_DOMAIN = "wifios.co.ke"
        operator = OperatorFactory(slug="acme")
        router = RouterFactory(operator=operator, provisioning_backend=Router.Backend.DUMMY)
        DummyAdapter.portal_fails = True

        with pytest.raises(ProvisioningError):
            push_portal_to_router(router.pk, domains.portal_url_for(operator))

        body = owner(operator).get(DOMAIN).json()
        row = body["routers"][0]
        assert row["on_current_domain"] is False
        assert row["error"]

    def test_a_move_clears_the_stale_synced_marker_immediately(self, settings):
        """Between the rename and the push landing, the router is on NEITHER address we
        would like to claim. It must not still show a tick from the last domain."""
        settings.PORTAL_BASE_URL = ""
        settings.TENANT_BASE_DOMAIN = "wifios.co.ke"
        operator = OperatorFactory(slug="acme")
        router = RouterFactory(operator=operator, provisioning_backend=Router.Backend.DUMMY)
        Router.objects.filter(pk=router.pk).update(
            portal_url="https://acme.wifios.co.ke", portal_synced_at=timezone.now()
        )

        operator.previous_slug, operator.slug = operator.slug, "acme-wifi"
        operator.slug_changed_at = timezone.now()
        operator.save()
        refresh_portal(operator)

        router.refresh_from_db()
        # refresh_portal cleared it; the task (eager in tests) then re-set it to the NEW url
        assert router.portal_url == "https://acme-wifi.wifios.co.ke"


def test_every_router_gets_its_own_isps_portal_address(settings):
    """Two ISPs, two domains. A router must never redirect a customer into another ISP's
    portal — that is a customer paying the wrong business."""
    settings.PORTAL_BASE_URL = ""
    settings.TENANT_BASE_DOMAIN = "wifios.co.ke"
    from apps.provisioning.onboarding import generate_setup_script

    acme = OperatorFactory(slug="acme")
    rival = OperatorFactory(slug="rival")

    acme_script = generate_setup_script(RouterFactory(operator=acme))
    rival_script = generate_setup_script(RouterFactory(operator=rival))

    assert "acme.wifios.co.ke" in acme_script
    assert "rival.wifios.co.ke" not in acme_script
    assert "rival.wifios.co.ke" in rival_script


def test_the_operator_holds_its_own_slug_without_blocking_itself():
    """An ISP re-checking their own name must not be told they have taken it."""
    operator = OperatorFactory(slug="acme")

    available, _ = domains.is_available("acme", exclude=operator)

    assert available is True
    assert Operator.objects.filter(slug="acme").exists()
