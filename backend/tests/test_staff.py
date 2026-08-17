"""Phase 3 of tenant RBAC: employee management. Owner/Admin create and run staff; role changes
and offboarding force-logout immediately; a new hire is made to change their temp password; the
org can require 2FA. The guardrails (never assign Owner/platform, never edit the owner or
yourself) are pinned here too.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.cookie_auth import make_refresh
from apps.accounts.models import Role, User

from .factories import OperatorFactory, UserFactory


def api_as(role, operator):
    user = UserFactory(role=role, operator=operator, is_staff=True)
    api = APIClient()
    api.force_authenticate(user=user)
    return api, user


def bearer(user):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {make_refresh(user).access_token}")
    return api


@pytest.fixture
def op(db):
    return OperatorFactory()


@pytest.mark.django_db
class TestStaffCrud:
    def test_owner_creates_an_employee_forced_to_reset_password(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        resp = owner_api.post(reverse("staff-list"), {
            "name": "New Tech", "phone": "254712000001",
            "role": Role.TENANT_TECHNICIAN, "password": "temp12345",
        })
        assert resp.status_code == 201, resp.data
        u = User.objects.get(phone="254712000001")
        assert u.operator_id == op.id
        assert u.is_staff and u.is_active and u.must_change_password
        assert u.role == Role.TENANT_TECHNICIAN
        assert u.check_password("temp12345")

    def test_care_and_technician_cannot_manage_staff(self, op):
        for role in (Role.TENANT_CARE, Role.TENANT_TECHNICIAN):
            api, _ = api_as(role, op)
            assert api.get(reverse("staff-list")).status_code == 403
            assert api.post(reverse("staff-list"), {}).status_code == 403

    def test_cannot_assign_owner_or_a_platform_role(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        for role in (Role.TENANT_OWNER, Role.PLATFORM_OWNER, Role.PLATFORM_SUPPORT):
            resp = owner_api.post(reverse("staff-list"), {
                "name": "X", "phone": "254712000009", "role": role, "password": "temp12345"})
            assert resp.status_code == 400, role

    def test_duplicate_phone_is_rejected(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        UserFactory(phone="254712000002", operator=op)
        resp = owner_api.post(reverse("staff-list"), {
            "name": "Dup", "phone": "254712000002",
            "role": Role.TENANT_CARE, "password": "temp12345"})
        assert resp.status_code == 400

    def test_role_change_revokes_the_employees_sessions(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        emp = UserFactory(role=Role.TENANT_CARE, operator=op, is_staff=True)
        before = emp.session_version
        resp = owner_api.patch(reverse("staff-detail", args=[emp.id]),
                               {"role": Role.TENANT_TECHNICIAN})
        assert resp.status_code == 200
        emp.refresh_from_db()
        assert emp.role == Role.TENANT_TECHNICIAN
        assert emp.session_version == before + 1

    def test_offboarding_deactivates_and_revokes(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        emp = UserFactory(role=Role.TENANT_CARE, operator=op, is_staff=True)
        before = emp.session_version
        resp = owner_api.delete(reverse("staff-detail", args=[emp.id]))
        assert resp.status_code == 204
        emp.refresh_from_db()
        assert emp.is_active is False
        assert emp.session_version == before + 1

    def test_owner_and_self_are_protected(self, op):
        owner_api, owner = api_as(Role.TENANT_OWNER, op)
        # cannot change yourself
        assert owner_api.patch(reverse("staff-detail", args=[owner.id]),
                               {"role": Role.TENANT_ADMIN}).status_code == 403
        # cannot change another owner via the staff screen
        other_owner = UserFactory(role=Role.TENANT_OWNER, operator=op, is_staff=True)
        assert owner_api.patch(reverse("staff-detail", args=[other_owner.id]),
                               {"role": Role.TENANT_ADMIN}).status_code == 403

    def test_reset_password_forces_change_and_logs_out(self, op):
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        emp = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, is_staff=True)
        before = emp.session_version
        resp = owner_api.post(reverse("staff-reset-password", args=[emp.id]),
                              {"password": "newtemp123"})
        assert resp.status_code == 200
        emp.refresh_from_db()
        assert emp.must_change_password and emp.check_password("newtemp123")
        assert emp.session_version == before + 1

    def test_tenant_isolation_hides_other_isps_staff(self, op):
        other_op = OperatorFactory()
        UserFactory(role=Role.TENANT_CARE, operator=other_op, is_staff=True)
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        data = owner_api.get(reverse("staff-list")).data
        rows = data["results"] if isinstance(data, dict) and "results" in data else data
        assert all(r["role"] != Role.PLATFORM_SUPPORT for r in rows)
        # every returned staff belongs to THIS operator
        ids = [r["id"] for r in rows]
        mine = User.objects.filter(operator=op, role__in=Role.tenant_roles())
        assert set(ids) == set(mine.values_list("id", flat=True))


@pytest.mark.django_db
class TestOnboardingSignals:
    def test_me_reports_forced_change_then_clears_after_change(self, op):
        emp = UserFactory(role=Role.TENANT_CARE, operator=op, is_staff=True,
                          must_change_password=True)
        emp.set_password("temp12345")
        emp.save()
        api = bearer(emp)
        assert api.get(reverse("me")).data["must_change_password"] is True
        resp = api.post(reverse("auth-change-password"),
                        {"current_password": "temp12345", "new_password": "brandnew123"})
        assert resp.status_code == 200
        emp.refresh_from_db()
        assert emp.must_change_password is False

    def test_me_must_enrol_2fa_follows_the_operator_switch(self, op):
        emp = UserFactory(role=Role.TENANT_TECHNICIAN, operator=op, is_staff=True)
        api = bearer(emp)
        assert api.get(reverse("me")).data["must_enrol_2fa"] is False
        op.enforce_staff_2fa = True
        op.save(update_fields=["enforce_staff_2fa"])
        assert api.get(reverse("me")).data["must_enrol_2fa"] is True

    def test_only_settings_writers_can_toggle_org_2fa(self, op):
        assert api_as(Role.TENANT_CARE, op)[0].patch(
            reverse("operator-settings"), {"enforce_staff_2fa": True}).status_code == 403
        owner_api, _ = api_as(Role.TENANT_OWNER, op)
        assert owner_api.patch(
            reverse("operator-settings"), {"enforce_staff_2fa": True}).status_code == 200
        op.refresh_from_db()
        assert op.enforce_staff_2fa is True
