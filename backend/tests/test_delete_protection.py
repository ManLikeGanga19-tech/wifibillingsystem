"""Deleting a row something else still depends on must fail CLEANLY (409), not 500. The
console now offers delete on plans, towers, routers, etc.; the ones that are PROTECT-
referenced (a plan with clients, a router with sessions) must refuse gracefully."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.pppoe.models import Client

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    ServicePlanFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def _staff(op):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER))
    return c


def test_deleting_a_plan_with_clients_returns_409_not_500():
    op = OperatorFactory()
    plan = ServicePlanFactory(operator=op)
    PppoeClientFactory(operator=op, plan=plan, status=Client.Status.ACTIVE)

    resp = _staff(op).delete(f"/api/v1/pppoe/plans/{plan.id}/")
    assert resp.status_code == 409
    assert "deleted" in str(resp.data).lower()


def test_deleting_an_unused_plan_succeeds():
    op = OperatorFactory()
    plan = ServicePlanFactory(operator=op)
    resp = _staff(op).delete(f"/api/v1/pppoe/plans/{plan.id}/")
    assert resp.status_code == 204
