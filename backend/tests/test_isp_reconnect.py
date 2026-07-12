"""The ISP reconnecting a paid customer who never got online.

The scenario Daniel raised: a payment came through (often via RECONCILIATION — the
callback was lost, stkpushquery confirmed it), but the customer never connected. Maybe
the router was down; maybe they walked away. The ISP needs to see "they paid, they're
not connected" and reconnect them from the dashboard — even far away, even after the
paid time has elapsed.

Because a human authorises this, it COMPENSATES: the customer paid for the full plan and
got nothing, so the clock restarts from the reconnection.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.payments.models import Transaction
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session

from .factories import OperatorFactory, RouterFactory, TransactionFactory, UserFactory

pytestmark = pytest.mark.django_db


def owner_client(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def paid_unconnected_tx(operator, router, *, reconciled=False, mins_ago=90):
    """A payment that came through but whose session failed / expired."""
    tx = TransactionFactory(
        operator=operator,
        status=Transaction.Status.RECONCILED if reconciled else Transaction.Status.SUCCESS,
    )
    now = timezone.now()
    Session.objects.create(
        operator=operator,
        plan=tx.plan,
        router=router,
        transaction=tx,
        hotspot_username=tx.phone,
        starts_at=now - timedelta(minutes=mins_ago),
        expires_at=now - timedelta(minutes=mins_ago - 60),  # window already closed
        status=Session.Status.FAILED,
        provision_error="router was down",
    )
    return tx


class TestTheUnconnectedQueue:
    def test_isp_sees_paid_but_unconnected_including_reconciled(self):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        paid_unconnected_tx(op, router, reconciled=True)
        # A normal, connected payment must NOT show in the queue.
        good = TransactionFactory(operator=op, status=Transaction.Status.SUCCESS)
        Session.objects.create(
            operator=op, plan=good.plan, router=router, transaction=good,
            hotspot_username=good.phone, starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1), status=Session.Status.ACTIVE,
        )

        resp = owner_client(op).get("/api/v1/payments/transactions/?unconnected=1")
        assert resp.status_code == 200
        rows = resp.json()["results"]
        assert len(rows) == 1
        assert rows[0]["provisioning"] == "failed"

    def test_the_queue_is_tenant_scoped(self):
        """One ISP must never see another's unconnected payments."""
        mine = OperatorFactory(slug="mine-isp")
        theirs = OperatorFactory(slug="theirs-isp")
        paid_unconnected_tx(theirs, RouterFactory(operator=theirs))

        resp = owner_client(mine).get("/api/v1/payments/transactions/?unconnected=1")
        assert resp.json()["results"] == []


class TestReconnect:
    def test_reconnect_compensates_with_a_fresh_full_window(
        self, django_capture_on_commit_callbacks
    ):
        op = OperatorFactory()
        router = RouterFactory(operator=op)
        tx = paid_unconnected_tx(op, router)
        session = tx.session
        old_expiry = session.expires_at
        assert old_expiry < timezone.now()  # their paid time is already gone

        with django_capture_on_commit_callbacks(execute=True):
            resp = owner_client(op).post(
                f"/api/v1/payments/transactions/{tx.id}/reconnect/"
            )
        assert resp.status_code == 200

        session.refresh_from_db()
        # A fresh full plan duration from NOW — they got zero for what they paid.
        assert session.expires_at > timezone.now()
        expected = timezone.now() + tx.plan.duration
        assert abs((session.expires_at - expected).total_seconds()) < 10
        assert session.status == Session.Status.ACTIVE  # eager: reconnected
        assert ("activate", tx.phone) in DummyAdapter.calls

    def test_reconnect_is_audited(self, django_capture_on_commit_callbacks):
        from apps.core.models import AuditLog

        op = OperatorFactory()
        tx = paid_unconnected_tx(op, RouterFactory(operator=op))
        with django_capture_on_commit_callbacks(execute=True):
            owner_client(op).post(f"/api/v1/payments/transactions/{tx.id}/reconnect/")

        assert AuditLog.objects.filter(action="session_reconnected", operator=op).exists()

    def test_cannot_reconnect_an_unpaid_transaction(self):
        op = OperatorFactory()
        RouterFactory(operator=op)
        tx = TransactionFactory(operator=op, status=Transaction.Status.PENDING)
        resp = owner_client(op).post(f"/api/v1/payments/transactions/{tx.id}/reconnect/")
        assert resp.status_code == 400

    def test_reconnect_with_no_router_gives_a_clear_error(self):
        op = OperatorFactory()  # no router
        tx = TransactionFactory(operator=op, status=Transaction.Status.SUCCESS)
        resp = owner_client(op).post(f"/api/v1/payments/transactions/{tx.id}/reconnect/")
        assert resp.status_code == 400
        assert "router" in resp.json()["detail"].lower()

    def test_one_isp_cannot_reconnect_anothers_transaction(self):
        theirs = OperatorFactory(slug="theirs-isp")
        tx = paid_unconnected_tx(theirs, RouterFactory(operator=theirs))
        # A different ISP's owner tries by guessing the id.
        resp = owner_client(OperatorFactory(slug="mine-isp")).post(
            f"/api/v1/payments/transactions/{tx.id}/reconnect/"
        )
        assert resp.status_code == 404  # tenant scoping hides it entirely
