"""The manual full-suspension — the human's last resort, deliberately outside the ladder.

The automatic ladder always leaves a door open (read-only + pay, so an ISP can self-cure).
A full suspension shuts that door: the console goes dark and only a person at Danamo can
reopen it. So the tests care about two things — that only the platform OWNER can pull this
lever, and that the ISP is told WHY (not left guessing), and that restore is a clean,
consistent reversal.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.core.models import Operator

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db


def platform_owner():
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=None, is_staff=True, is_superuser=True,
                         role=Role.PLATFORM_OWNER)
    )
    return c


def platform_support():
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=None, is_staff=True, role=Role.PLATFORM_SUPPORT)
    )
    return c


def test_the_platform_owner_can_suspend_with_a_reason():
    op = OperatorFactory(slug="deadbeat", status=Operator.Status.ACTIVE)

    resp = platform_owner().post(
        f"/api/v1/platform/tenants/{op.id}/suspend/",
        {"reason": "Unpaid for 60 days despite reminders."}, format="json",
    )

    assert resp.status_code == 200
    op.refresh_from_db()
    assert op.status == Operator.Status.SUSPENDED
    assert op.suspension_reason == "Unpaid for 60 days despite reminders."
    assert op.is_operational is False  # the console is fully dark now


def test_the_suspension_reason_is_shown_to_the_isp_not_a_generic_message():
    """A suspended-for-non-payment ISP must be told to settle, not left to guess."""
    op = OperatorFactory(slug="told", status=Operator.Status.ACTIVE)
    owner = UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
    platform_owner().post(
        f"/api/v1/platform/tenants/{op.id}/suspend/",
        {"reason": "Settle KSh 8,000 to be reinstated."}, format="json",
    )

    from apps.accounts.models import User

    c = APIClient()
    # Re-fetch so the user's cached .operator reflects the suspension (a real request loads
    # the user fresh from the DB; force_authenticate with a stale instance would not).
    c.force_authenticate(user=User.objects.get(pk=owner.pk))
    me = c.get("/api/v1/me/").json()

    blocker = me["operator"]["go_live_blockers"][0]
    assert blocker["key"] == "suspended"
    assert "Settle KSh 8,000" in blocker["detail"]


def test_restore_brings_them_back_cleanly():
    op = OperatorFactory(slug="comeback", status=Operator.Status.ACTIVE)
    platform_owner().post(f"/api/v1/platform/tenants/{op.id}/suspend/",
                          {"reason": "test"}, format="json")

    resp = platform_owner().post(f"/api/v1/platform/tenants/{op.id}/restore/")

    assert resp.status_code == 200
    op.refresh_from_db()
    assert op.status == Operator.Status.ACTIVE
    assert op.suspension_reason == ""
    assert op.is_operational is True


def test_restore_only_applies_to_a_suspended_tenant():
    op = OperatorFactory(slug="active", status=Operator.Status.ACTIVE)

    resp = platform_owner().post(f"/api/v1/platform/tenants/{op.id}/restore/")

    assert resp.status_code == 400


def test_platform_SUPPORT_cannot_suspend_or_restore():
    """Cutting off (or reinstating) a business is an OWNER decision, not support's."""
    op = OperatorFactory(slug="protected", status=Operator.Status.ACTIVE)

    assert platform_support().post(
        f"/api/v1/platform/tenants/{op.id}/suspend/", {"reason": "x"}, format="json"
    ).status_code == 403

    op.status = Operator.Status.SUSPENDED
    op.save()
    assert platform_support().post(
        f"/api/v1/platform/tenants/{op.id}/restore/"
    ).status_code == 403


def test_an_isp_cannot_suspend_itself_or_anyone():
    """This lever lives on the PLATFORM console. An ISP owner has no reach here."""
    op = OperatorFactory(slug="isp", status=Operator.Status.ACTIVE)
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER))

    resp = c.post(f"/api/v1/platform/tenants/{op.id}/suspend/", {"reason": "x"}, format="json")

    assert resp.status_code == 403
    op.refresh_from_db()
    assert op.status == Operator.Status.ACTIVE
