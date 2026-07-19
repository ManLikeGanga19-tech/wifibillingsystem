"""Settings > Password & 2FA: the change-password endpoint. (The authenticator/TOTP flow already
has coverage in test_mfa.py.)"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role

from .factories import UserFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/auth/change-password/"


def _user(password="oldpassword1"):
    user = UserFactory(is_staff=True, role=Role.TENANT_OWNER)
    user.set_password(password)
    user.save()
    return user


def _auth(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestChangePassword:
    def test_success_actually_changes_the_password(self):
        user = _user("oldpassword1")
        resp = _auth(user).post(
            URL, {"current_password": "oldpassword1", "new_password": "brandNewpass9"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        user.refresh_from_db()
        assert user.check_password("brandNewpass9")
        assert not user.check_password("oldpassword1")

    def test_wrong_current_password_is_rejected(self):
        user = _user("oldpassword1")
        resp = _auth(user).post(
            URL, {"current_password": "nope", "new_password": "brandNewpass9"},
            format="json",
        )
        assert resp.status_code == 400
        user.refresh_from_db()
        assert user.check_password("oldpassword1")  # unchanged

    def test_too_short_new_password_is_rejected(self):
        user = _user("oldpassword1")
        resp = _auth(user).post(
            URL, {"current_password": "oldpassword1", "new_password": "short"},
            format="json",
        )
        assert resp.status_code == 400
        user.refresh_from_db()
        assert user.check_password("oldpassword1")

    def test_requires_authentication(self):
        assert APIClient().post(
            URL, {"current_password": "x", "new_password": "yyyyyyyy"}, format="json"
        ).status_code == 401

    def test_writes_an_audit_line(self):
        from apps.core.models import AuditLog

        user = _user("oldpassword1")
        _auth(user).post(
            URL, {"current_password": "oldpassword1", "new_password": "brandNewpass9"},
            format="json",
        )
        assert AuditLog.objects.filter(action="password_changed", actor=user).exists()
