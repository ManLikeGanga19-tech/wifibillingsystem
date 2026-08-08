"""Churn & retention: the lifecycle-event log, the auto-cancel ageing rule, and the
churn-summary analytics endpoint. Point-in-time status can't answer "who left in July";
these prove the dated trail that can."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.pppoe.lifecycle import cancel_stale_suspended_clients
from apps.pppoe.models import Client, ClientLifecycleEvent, PppoeSettings
from apps.pppoe.services import (
    cancel_client,
    provision_client,
    restore_client,
    suspend_client,
)

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    RouterFactory,
    ServicePlanFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def staff(operator, role=Role.TENANT_OWNER):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=role))
    return c


def _pending(op):
    return PppoeClientFactory(operator=op, status=Client.Status.PENDING_INSTALL)


class TestLifecycleEventsAreRecorded:
    def test_full_journey_logs_every_transition(self):
        op = OperatorFactory()
        client = _pending(op)

        provision_client(client)  # pending -> active
        suspend_client(client, reason="overdue")  # active -> suspended
        restore_client(client)  # suspended -> active (paid)
        suspend_client(client)  # active -> suspended again
        cancel_client(client, reason="gave up")  # suspended -> cancelled

        events = list(
            ClientLifecycleEvent.objects.filter(client=client).order_by("occurred_at")
        )
        E = ClientLifecycleEvent.Event
        assert [e.event for e in events] == [
            E.ACTIVATED, E.SUSPENDED, E.RESTORED, E.SUSPENDED, E.CANCELLED
        ]
        client.refresh_from_db()
        assert client.status == Client.Status.CANCELLED
        assert client.status_changed_at is not None
        # every event carries the account snapshot, so it survives a later delete
        assert all(e.account_number == client.account_number for e in events)

    def test_reprovisioning_a_churned_client_is_a_reactivation(self):
        op = OperatorFactory()
        client = _pending(op)
        provision_client(client)
        suspend_client(client)
        cancel_client(client)

        provision_client(client)  # won back

        client.refresh_from_db()
        assert client.status == Client.Status.ACTIVE
        assert ClientLifecycleEvent.objects.filter(
            client=client, event=ClientLifecycleEvent.Event.REACTIVATED
        ).exists()

    def test_cancel_only_applies_to_suspended(self):
        op = OperatorFactory()
        client = _pending(op)
        provision_client(client)  # active, not suspended
        cancel_client(client)
        client.refresh_from_db()
        assert client.status == Client.Status.ACTIVE  # untouched

    def test_events_survive_client_deletion(self):
        op = OperatorFactory()
        client = _pending(op)
        provision_client(client)
        suspend_client(client)
        cancel_client(client)
        acct = client.account_number

        client.delete()

        surviving = ClientLifecycleEvent.objects.filter(operator=op, account_number=acct)
        assert surviving.filter(event=ClientLifecycleEvent.Event.CANCELLED).exists()
        assert surviving.first().client_id is None  # tombstone: FK nulled, row kept


class TestAutoCancelAgeingRule:
    def _suspended_since(self, op, days_ago):
        client = _pending(op)
        provision_client(client)
        suspend_client(client)
        # backdate the suspension
        when = timezone.now() - timedelta(days=days_ago)
        Client.objects.filter(pk=client.pk).update(status_changed_at=when)
        return client

    def test_opt_in_and_only_past_threshold(self):
        op = OperatorFactory()
        PppoeSettings.objects.create(operator=op, churn_after_suspended_days=60)
        old = self._suspended_since(op, 70)
        fresh = self._suspended_since(op, 10)

        assert cancel_stale_suspended_clients() == 1

        old.refresh_from_db()
        fresh.refresh_from_db()
        assert old.status == Client.Status.CANCELLED
        assert fresh.status == Client.Status.SUSPENDED  # not yet past 60 days

    def test_never_cancels_when_unset(self):
        op = OperatorFactory()
        # no PppoeSettings row / threshold = the safe default: never auto-cancel
        self._suspended_since(op, 400)
        assert cancel_stale_suspended_clients() == 0

    def test_isolated_per_operator_threshold(self):
        op_a = OperatorFactory(slug="churn-a")
        op_b = OperatorFactory(slug="churn-b")
        PppoeSettings.objects.create(operator=op_a, churn_after_suspended_days=30)
        # op_b has NO threshold; its stale client must be left alone
        a = self._suspended_since(op_a, 45)
        b = self._suspended_since(op_b, 45)

        cancel_stale_suspended_clients()

        a.refresh_from_db()
        b.refresh_from_db()
        assert a.status == Client.Status.CANCELLED
        assert b.status == Client.Status.SUSPENDED


class TestChurnSummaryEndpoint:
    def test_counts_current_month_movement_and_standing(self):
        op = OperatorFactory()
        plan = ServicePlanFactory(operator=op)
        router = RouterFactory(operator=op)

        def new_client():
            c = PppoeClientFactory(
                operator=op, plan=plan, router=router,
                status=Client.Status.PENDING_INSTALL,
            )
            provision_client(c)
            return c

        new_client()
        new_client()  # 2 activations that stay
        leaver = new_client()  # activated then churns this month
        suspend_client(leaver)
        cancel_client(leaver)

        body = staff(op).get("/api/v1/pppoe/churn-summary/?months=3").json()

        assert len(body["months"]) == 3
        current = body["months"][-1]  # newest month last
        assert current["new"] == 3
        assert current["churned"] == 1
        assert current["net"] == 2  # 3 new - 1 churned
        assert body["standing"]["active"] == 2  # keep1, keep2
        assert body["standing"]["cancelled"] == 1
        # churn rate: nobody was in the base at the START of this month (all joined mid-month)
        assert current["active_start"] == 0
        assert current["churn_rate"] is None

    def test_endpoint_is_tenant_scoped(self):
        op = OperatorFactory(slug="churn-me")
        other = OperatorFactory(slug="churn-other")
        c = _pending(other)
        provision_client(c)
        suspend_client(c)
        cancel_client(c)  # churn belongs to `other`

        body = staff(op).get("/api/v1/pppoe/churn-summary/").json()
        assert all(m["churned"] == 0 for m in body["months"])
        assert body["standing"]["cancelled"] == 0
