"""Platform system health.

The checks are ranked by what actually hurts. The one that matters most:
a customer who PAID and has no internet.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.payments.models import C2BPayment, Transaction
from apps.provisioning.models import Router, Session

from .factories import (
    OperatorFactory,
    RouterFactory,
    SessionFactory,
    TransactionFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def platform():
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(
            operator=None, is_staff=True, is_superuser=True, role=Role.PLATFORM_OWNER
        )
    )
    return c


def health():
    return platform().get("/api/v1/platform/health/").json()


def check(data, key):
    return next(c for c in data["checks"] if c["key"] == key)


class TestOverallState:
    def test_clean_system_is_ok_except_workers(self):
        """With no stranded money and no fleet, only the worker check can fail
        (Celery isn't running under pytest)."""
        data = health()
        assert check(data, "stuck_payments")["state"] == "ok"
        assert check(data, "unmatched_payments")["state"] == "ok"
        assert check(data, "undelivered_service")["state"] == "ok"

    def test_worst_check_decides_overall(self):
        # An unmatched payment is critical -> the whole board is critical
        C2BPayment.objects.create(
            trans_id="ORPHAN", bill_ref="NOPE", amount=Decimal("500"),
            status=C2BPayment.Status.UNMATCHED,
        )
        assert health()["status"] == "crit"

    def test_requires_platform_staff(self):
        op = OperatorFactory()
        c = APIClient()
        c.force_authenticate(
            user=UserFactory(operator=op, is_staff=True, role=Role.TENANT_OWNER)
        )
        assert c.get("/api/v1/platform/health/").status_code == 403


class TestMoneyStranded:
    def test_unmatched_payment_is_critical_and_totals_the_value(self):
        C2BPayment.objects.create(
            trans_id="A1", bill_ref="GHOST", amount=Decimal("2000"),
            status=C2BPayment.Status.UNMATCHED,
        )
        C2BPayment.objects.create(
            trans_id="A2", bill_ref="GHOST2", amount=Decimal("1500"),
            status=C2BPayment.Status.UNMATCHED,
        )
        data = health()
        c = check(data, "unmatched_payments")
        assert c["state"] == "crit"
        assert c["value"] == 2
        assert Decimal(str(data["money"]["unmatched_value"])) == Decimal("3500")

    def test_stuck_pending_payment_warns(self):
        tx = TransactionFactory(status=Transaction.Status.PENDING)
        Transaction.objects.filter(pk=tx.pk).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
        c = check(health(), "stuck_payments")
        assert c["state"] == "warn"
        assert c["value"] == 1

    def test_a_fresh_pending_payment_is_not_stuck(self):
        TransactionFactory(status=Transaction.Status.PENDING)  # just now
        assert check(health(), "stuck_payments")["state"] == "ok"

    def test_paid_customer_with_no_service_is_critical(self):
        """The worst failure mode: money taken, internet not delivered."""
        SessionFactory(status=Session.Status.FAILED)
        c = check(health(), "undelivered_service")
        assert c["state"] == "crit"
        assert c["value"] == 1

    def test_session_stuck_pending_counts_as_undelivered(self):
        s = SessionFactory(status=Session.Status.PENDING)
        Session.objects.filter(pk=s.pk).update(
            created_at=timezone.now() - timedelta(minutes=30)
        )
        assert check(health(), "undelivered_service")["value"] == 1

    def test_a_fresh_pending_session_is_not_yet_a_failure(self):
        SessionFactory(status=Session.Status.PENDING)  # provisioning may be in flight
        assert check(health(), "undelivered_service")["state"] == "ok"


class TestFleet:
    def test_offline_router_warns(self):
        RouterFactory(status=Router.Status.ONLINE)
        RouterFactory(status=Router.Status.OFFLINE)
        data = health()
        assert check(data, "routers_offline")["state"] == "warn"
        assert data["fleet"]["offline"] == 1
        assert data["fleet"]["online"] == 1

    def test_whole_fleet_offline_is_critical(self):
        RouterFactory(status=Router.Status.OFFLINE)
        RouterFactory(status=Router.Status.OFFLINE)
        assert check(health(), "routers_offline")["state"] == "crit"

    def test_router_needing_reonboarding_is_surfaced(self):
        RouterFactory(status=Router.Status.ONLINE, onboarding_required=True)
        data = health()
        c = check(data, "routers_reonboard")
        assert c["state"] == "warn"
        assert data["fleet"]["needs_reonboarding"] == 1


class TestWorkers:
    def test_worker_check_reports_a_coherent_state(self):
        """Whether or not a broker is up in this environment, the check must
        return a coherent answer — and it must never raise or hang. A health
        check that hangs is worse than one that reports failure."""
        data = health()
        w = data["workers"]
        assert isinstance(w["reachable"], bool)
        assert w["count"] == len(w["names"])
        # reachable <=> ok, unreachable <=> crit. No third story.
        assert check(data, "workers")["state"] == ("ok" if w["reachable"] else "crit")

    def test_a_dead_broker_reports_crit_instead_of_exploding(self, monkeypatch):
        from config.celery import app as celery_app

        def boom(**_kwargs):
            raise OSError("broker unreachable")

        monkeypatch.setattr(celery_app.control, "ping", boom)
        data = health()
        assert data["workers"]["reachable"] is False
        assert check(data, "workers")["state"] == "crit"
        assert data["status"] == "crit"
