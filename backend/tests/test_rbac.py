"""Phase 1 (the spine) of tenant RBAC: the capability map, the RequireCapability gate, the
money invariant, and immediate session revocation. The permission matrix in the design spec is
the human-readable form of what these tests pin down.
"""

import pytest
from rest_framework.test import APIClient, APIRequestFactory

from apps.accounts import rbac
from apps.accounts.cookie_auth import make_refresh
from apps.accounts.models import Role
from apps.core.permissions import RequireCapability

from .factories import UserFactory


@pytest.mark.django_db
class TestCapabilityMap:
    """The role -> capability map is the single source of truth; assert each role's exact reach."""

    def test_owner_has_everything_including_money(self):
        u = UserFactory(role=Role.TENANT_OWNER)
        assert set(u.capabilities) == set(rbac.ALL_TENANT_CAPS)
        assert u.has_capability(rbac.MONEY_MANAGE)

    def test_admin_is_owner_minus_non_delegable(self):
        u = UserFactory(role=Role.TENANT_ADMIN)
        # Admin gets everything EXCEPT the two non-delegable powers (move money, edit permissions).
        assert set(u.capabilities) == set(rbac.ALL_TENANT_CAPS) - rbac.NON_DELEGABLE
        assert not u.has_capability(rbac.MONEY_MANAGE)
        assert not u.has_capability(rbac.RBAC_MANAGE)
        # but a full operator otherwise — routers, network, plans, staff
        assert u.has_capability(rbac.NETWORK_WRITE)
        assert u.has_capability(rbac.ROUTER_ACCESS)
        assert u.has_capability(rbac.HOTSPOT_PLANS)
        assert u.has_capability(rbac.STAFF_MANAGE)

    def test_care_is_the_front_desk(self):
        u = UserFactory(role=Role.TENANT_CARE)
        assert u.has_capability(rbac.CLIENTS_PLAN)
        assert u.has_capability(rbac.HOTSPOT_VOUCHERS)   # issue vouchers on the desk
        assert u.has_capability(rbac.PAYMENTS_STATUS)
        assert u.has_capability(rbac.TICKETS_ASSIGN)
        assert u.has_capability(rbac.LEADS_WRITE)
        assert u.has_capability(rbac.MESSAGING_SEND)
        # never the books, the network, plan config, or the money
        assert not u.has_capability(rbac.PAYMENTS_VIEW_AMOUNTS)
        assert not u.has_capability(rbac.HOTSPOT_PLANS)
        assert not u.has_capability(rbac.NETWORK_WRITE)
        assert not u.has_capability(rbac.ROUTER_ACCESS)
        assert not u.has_capability(rbac.SETTINGS_WRITE)
        assert not u.has_capability(rbac.MONEY_MANAGE)
        assert not u.has_capability(rbac.STAFF_MANAGE)

    def test_technician_is_field_ops(self):
        u = UserFactory(role=Role.TENANT_TECHNICIAN)
        assert u.has_capability(rbac.NETWORK_WRITE)
        assert u.has_capability(rbac.ROUTER_ACCESS)
        assert u.has_capability(rbac.CLIENTS_FIELD)     # status/location, not the whole record
        assert u.has_capability(rbac.LEADS_VIEW)        # read-only, map layer
        assert u.has_capability(rbac.MAP_VIEW)
        # not the CRM, plan changes, ticket assignment, payments, or money
        assert not u.has_capability(rbac.LEADS_WRITE)
        assert not u.has_capability(rbac.CLIENTS_WRITE)
        assert not u.has_capability(rbac.CLIENTS_PLAN)
        assert not u.has_capability(rbac.TICKETS_ASSIGN)
        assert not u.has_capability(rbac.PAYMENTS_STATUS)
        assert not u.has_capability(rbac.HOTSPOT_VOUCHERS)
        assert not u.has_capability(rbac.MONEY_MANAGE)

    def test_platform_support_is_read_only(self):
        u = UserFactory(role=Role.PLATFORM_SUPPORT, operator=None)
        assert set(u.capabilities) == set(rbac.READ_ONLY_CAPS)
        assert not any(c.endswith(".write") for c in u.capabilities)
        assert not u.has_capability(rbac.MONEY_MANAGE)
        assert not u.has_capability(rbac.NETWORK_WRITE)

    def test_platform_owner_has_full_tenant_power(self):
        u = UserFactory(role=Role.PLATFORM_OWNER, operator=None)
        assert set(u.capabilities) == set(rbac.ALL_TENANT_CAPS)


@pytest.mark.django_db
class TestMoneyInvariant:
    """Adding delegated roles must NEVER widen who can move money. Owner-only, forever."""

    @pytest.mark.parametrize(
        "role,expected",
        [
            (Role.TENANT_OWNER, True),
            (Role.TENANT_ADMIN, False),
            (Role.TENANT_CARE, False),
            (Role.TENANT_TECHNICIAN, False),
            (Role.PLATFORM_OWNER, True),
            (Role.PLATFORM_SUPPORT, False),
        ],
    )
    def test_can_manage_money(self, role, expected):
        assert UserFactory(role=role).can_manage_money is expected


@pytest.mark.django_db
class TestRequireCapabilityGate:
    """Layer A: the DRF gate resolves a role against a single capability string."""

    def _req(self, user, method="post"):
        req = getattr(APIRequestFactory(), method)("/x")
        req.user = user
        return req

    def test_allows_when_capability_present(self):
        perm = RequireCapability(rbac.NETWORK_WRITE)
        tech = UserFactory(role=Role.TENANT_TECHNICIAN)
        assert perm.has_permission(self._req(tech), None) is True

    def test_denies_when_capability_absent(self):
        perm = RequireCapability(rbac.NETWORK_WRITE)
        care = UserFactory(role=Role.TENANT_CARE)
        assert perm.has_permission(self._req(care), None) is False

    def test_read_split_lets_technician_read_but_not_write_leads(self):
        perm = RequireCapability(rbac.LEADS_WRITE, read=rbac.LEADS_VIEW)
        tech = UserFactory(role=Role.TENANT_TECHNICIAN)
        assert perm.has_permission(self._req(tech, "get"), None) is True    # read-only ok
        assert perm.has_permission(self._req(tech, "post"), None) is False  # write refused


@pytest.mark.django_db
class TestSessionRevocation:
    """Bumping session_version voids every issued token at once (both auth paths run get_user)."""

    def _bearer(self, user):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {make_refresh(user).access_token}")
        return c

    def test_token_valid_until_bumped(self):
        from django.urls import reverse

        user = UserFactory(is_staff=True, role=Role.TENANT_OWNER)
        client = self._bearer(user)
        me = reverse("me")

        assert client.get(me).status_code == 200

        # A role downgrade / offboarding calls this — the live token must die at once.
        user.revoke_sessions()
        assert client.get(me).status_code == 401

    def test_fresh_token_after_bump_works_again(self):
        from django.urls import reverse

        user = UserFactory(is_staff=True, role=Role.TENANT_OWNER)
        user.revoke_sessions()
        # a token minted AFTER the bump carries the new epoch and is accepted
        client = self._bearer(user)
        assert client.get(reverse("me")).status_code == 200
