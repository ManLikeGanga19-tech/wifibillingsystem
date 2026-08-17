"""Owner-editable role permissions: the per-tenant override changes what a role can do, the
non-delegable powers can never be granted, and only the Owner may edit."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import OperatorRoleConfig, Role

from .factories import OperatorFactory, UserFactory


def api_as(role, operator):
    user = UserFactory(role=role, operator=operator, is_staff=True)
    api = APIClient()
    api.force_authenticate(user=user)
    return api, user


@pytest.fixture
def op(db):
    return OperatorFactory()


@pytest.mark.django_db
class TestOverrideChangesCapabilities:
    def test_override_replaces_the_default_set(self, op):
        tech = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op)
        assert tech.has_capability(rbac.NETWORK_WRITE)          # default technician
        # Owner strips the technician down to just the map.
        OperatorRoleConfig.objects.create(operator=op, role=Role.TENANT_TECHNICIAN,
                                          capabilities=[rbac.MAP_VIEW])
        tech.refresh_from_db()
        assert set(tech.capabilities) == {rbac.MAP_VIEW}
        assert not tech.has_capability(rbac.NETWORK_WRITE)

    def test_override_is_scoped_to_its_tenant(self, op):
        other = OperatorFactory(slug="other-isp")   # distinct tenant (factory keys on slug)
        OperatorRoleConfig.objects.create(operator=op, role=Role.TENANT_CARE,
                                          capabilities=[rbac.MAP_VIEW])
        here = UserFactory(role=Role.TENANT_CARE, operator=op)
        there = UserFactory(role=Role.TENANT_CARE, operator=other)
        assert set(here.capabilities) == {rbac.MAP_VIEW}
        assert there.has_capability(rbac.CLIENTS_WRITE)         # untouched — still default

    def test_non_delegable_powers_are_stripped_from_any_override(self, op):
        # Even if a row somehow contains money.manage / rbac.manage, capabilities_for drops them.
        OperatorRoleConfig.objects.create(
            operator=op, role=Role.TENANT_ADMIN,
            capabilities=[rbac.MONEY_MANAGE, rbac.RBAC_MANAGE, rbac.CLIENTS_VIEW],
        )
        admin = UserFactory(role=Role.TENANT_ADMIN, operator=op)
        assert admin.has_capability(rbac.CLIENTS_VIEW)
        assert not admin.has_capability(rbac.MONEY_MANAGE)
        assert not admin.has_capability(rbac.RBAC_MANAGE)


@pytest.mark.django_db
class TestAccessControlApi:
    def test_owner_reads_catalogue_and_roles(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        data = owner_api.get(reverse("rbac-access-control")).data
        assert {r["role"] for r in data["roles"]} == set(rbac.CONFIGURABLE_ROLES)
        assert rbac.MONEY_MANAGE in data["non_delegable"]
        # every catalogue entry is an assignable capability
        assert {c["capability"] for c in data["catalog"]} <= set(rbac.ASSIGNABLE_CAPS)

    def test_only_owner_can_open_access_control(self, op):
        for role in (Role.TENANT_ADMIN, Role.TENANT_CARE, Role.TENANT_TECHNICIAN):
            api, _ = api_as(role, op)
            assert api.get(reverse("rbac-access-control")).status_code == 403

    def test_owner_sets_a_roles_permissions(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        resp = owner_api.put(reverse("rbac-role", args=[Role.TENANT_CARE]),
                             {"capabilities": [rbac.CLIENTS_VIEW, rbac.MAP_VIEW]}, format="json")
        assert resp.status_code == 200
        assert set(resp.data["capabilities"]) == {rbac.CLIENTS_VIEW, rbac.MAP_VIEW}
        assert resp.data["is_custom"] is True
        care = UserFactory(role=Role.TENANT_CARE, operator=op)
        assert set(care.capabilities) == {rbac.CLIENTS_VIEW, rbac.MAP_VIEW}

    def test_put_drops_non_delegable_and_unknown_capabilities(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        resp = owner_api.put(
            reverse("rbac-role", args=[Role.TENANT_ADMIN]),
            {"capabilities": [rbac.CLIENTS_VIEW, rbac.MONEY_MANAGE, "made.up"]}, format="json")
        assert resp.status_code == 200
        assert set(resp.data["capabilities"]) == {rbac.CLIENTS_VIEW}

    def test_owner_role_is_not_configurable(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        resp = owner_api.put(reverse("rbac-role", args=[Role.TENANT_OWNER]),
                             {"capabilities": [rbac.MAP_VIEW]}, format="json")
        assert resp.status_code == 400

    def test_reset_restores_defaults(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        OperatorRoleConfig.objects.create(operator=op, role=Role.TENANT_TECHNICIAN,
                                          capabilities=[rbac.MAP_VIEW])
        resp = owner_api.delete(reverse("rbac-role", args=[Role.TENANT_TECHNICIAN]))
        assert resp.status_code == 200
        assert resp.data["is_custom"] is False
        default = rbac.default_capabilities(Role.TENANT_TECHNICIAN)
        assert set(resp.data["capabilities"]) == set(default)
        assert not OperatorRoleConfig.objects.filter(
            operator=op, role=Role.TENANT_TECHNICIAN).exists()
