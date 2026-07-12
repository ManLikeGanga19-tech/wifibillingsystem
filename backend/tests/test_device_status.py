"""Device status for the auto-renew prompt.

When a hotspot customer's time runs out, the router cuts them off and — the moment they
next open a browser — redirects them back to the portal. This endpoint is how the portal
greets that returning device: "your <plan> ended, renew?" instead of a cold plan list.

It is keyed by MAC and returns NO phone number, on purpose: a MAC is trivially spoofable
on an open hotspot, so returning the phone would be a way to harvest customers' numbers.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.provisioning.models import Session

from .factories import OperatorFactory, PlanFactory, RouterFactory, TransactionFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/payments/device-status/"
MAC = "AA:BB:CC:DD:EE:FF"


def _session(operator, router, *, status, mins):
    plan = PlanFactory(operator=operator, name="1 Hour Express")
    tx = TransactionFactory(operator=operator, plan=plan)
    now = timezone.now()
    expires = now + timedelta(minutes=mins) if status == "active" else now - timedelta(minutes=1)
    return Session.objects.create(
        operator=operator, plan=plan, router=router, transaction=tx,
        hotspot_username="254700000000", mac_address=MAC,
        starts_at=now - timedelta(minutes=mins),
        expires_at=expires,
        status=Session.Status.ACTIVE if status == "active" else Session.Status.EXPIRED,
    )


class TestDeviceStatus:
    def test_expired_device_gets_a_renewal_prompt(self, api_client):
        op = OperatorFactory()
        r = RouterFactory(operator=op)
        _session(op, r, status="expired", mins=60)

        body = api_client.get(f"{URL}?mac={MAC}&router={r.id}").json()
        assert body["found"] is True
        assert body["expired"] is True
        assert body["plan_name"] == "1 Hour Express"
        assert "phone" not in body  # never leak a number keyed by a spoofable MAC

    def test_an_active_device_is_not_prompted_to_renew(self, api_client):
        op = OperatorFactory()
        r = RouterFactory(operator=op)
        _session(op, r, status="active", mins=30)

        body = api_client.get(f"{URL}?mac={MAC}&router={r.id}").json()
        assert body["found"] is True
        assert body["active"] is True
        assert body["expired"] is False

    def test_an_unknown_device_gets_nothing(self, api_client):
        r = RouterFactory()
        body = api_client.get(f"{URL}?mac=11:22:33:44:55:66&router={r.id}").json()
        assert body["found"] is False

    def test_it_is_scoped_to_the_router_operator(self, api_client):
        """A device that used ISP A must not surface when querying at ISP B's router."""
        a = OperatorFactory(slug="isp-a")
        b = OperatorFactory(slug="isp-b")
        _session(a, RouterFactory(operator=a), status="expired", mins=60)
        r_b = RouterFactory(operator=b)

        body = api_client.get(f"{URL}?mac={MAC}&router={r_b.id}").json()
        assert body["found"] is False

    def test_no_mac_is_a_clean_miss_not_an_error(self, api_client):
        r = RouterFactory()
        resp = api_client.get(f"{URL}?router={r.id}")
        assert resp.status_code == 200
        assert resp.json()["found"] is False

    def test_the_most_recent_session_wins(self, api_client):
        """A device that renewed several times should reflect its LATEST session."""
        op = OperatorFactory()
        r = RouterFactory(operator=op)
        _session(op, r, status="expired", mins=180)  # old
        _session(op, r, status="active", mins=20)  # current

        body = api_client.get(f"{URL}?mac={MAC}&router={r.id}").json()
        assert body["active"] is True  # not the stale expired one
