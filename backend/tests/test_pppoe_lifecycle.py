"""Settings > PPPoE: the three lifecycle behaviours that drive real backbone work.

The settings are only worth anything if they change what the tasks do. So each test drives
the ACTUAL task (prune / remind / invoice) through the setting, and the pruning tests lean
hard on the safety rules — deletion is irreversible and money-adjacent.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.notifications.providers.dummy import DummyProvider
from apps.pppoe.lifecycle import prune_dormant_clients, remind_expiring_clients
from apps.pppoe.models import Client, Invoice, PppoeSettings
from apps.pppoe.services import issue_invoice
from apps.pppoe.tasks import issue_due_invoices

from .factories import OperatorFactory, PppoeClientFactory, UserFactory

pytestmark = pytest.mark.django_db

SETTINGS_URL = "/api/v1/pppoe/settings/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def make_dormant(client, days):
    """Force a client's last-touched timestamp into the past."""
    Client.objects.filter(pk=client.pk).update(
        updated_at=timezone.now() - timedelta(days=days)
    )


# --- pruning: conservative by design ----------------------------------------------------


def test_pruning_is_off_by_default():
    """Deletion is opt-in — an ISP on the defaults never loses an account."""
    operator = OperatorFactory(slug="safe")
    client = PppoeClientFactory(operator=operator, status=Client.Status.DISABLED)
    make_dormant(client, 400)

    assert prune_dormant_clients() == 0
    assert Client.objects.filter(pk=client.pk).exists()


def test_a_dormant_disabled_account_with_no_invoices_is_pruned():
    operator = OperatorFactory(slug="prune")
    PppoeSettings.objects.create(operator=operator, inactive_prune_days=30)
    client = PppoeClientFactory(operator=operator, status=Client.Status.DISABLED)
    make_dormant(client, 45)

    assert prune_dormant_clients() == 1
    assert not Client.objects.filter(pk=client.pk).exists()


def test_a_client_with_ANY_invoice_is_never_pruned():
    """A billed customer is a financial record. We tidy the list by leaving them alone,
    never by destroying the books."""
    operator = OperatorFactory(slug="hasbill")
    PppoeSettings.objects.create(operator=operator, inactive_prune_days=30)
    client = PppoeClientFactory(operator=operator, status=Client.Status.DISABLED,
                                plan__price=Decimal("2000.00"))
    issue_invoice(client, timezone.localdate())
    make_dormant(client, 90)

    assert prune_dormant_clients() == 0
    assert Client.objects.filter(pk=client.pk).exists()


def test_active_and_suspended_accounts_are_never_pruned():
    operator = OperatorFactory(slug="live")
    PppoeSettings.objects.create(operator=operator, inactive_prune_days=7)
    active = PppoeClientFactory(operator=operator, status=Client.Status.ACTIVE)
    suspended = PppoeClientFactory(operator=operator, status=Client.Status.SUSPENDED)
    for c in (active, suspended):
        make_dormant(c, 400)

    assert prune_dormant_clients() == 0
    assert Client.objects.filter(pk__in=[active.pk, suspended.pk]).count() == 2


def test_a_recently_touched_dormant_account_is_kept():
    operator = OperatorFactory(slug="recent")
    PppoeSettings.objects.create(operator=operator, inactive_prune_days=30)
    client = PppoeClientFactory(operator=operator, status=Client.Status.DISABLED)
    make_dormant(client, 10)  # inside the 30-day window

    assert prune_dormant_clients() == 0


# --- pre-expiry reminders ---------------------------------------------------------------


def test_a_subscriber_is_reminded_before_renewal_once_per_cycle():
    operator = OperatorFactory(slug="remind")
    PppoeSettings.objects.create(operator=operator, pre_expiry_reminder_hours=[24, 72])
    DummyProvider.sent = []
    client = PppoeClientFactory(
        operator=operator, status=Client.Status.ACTIVE, phone="254700000001",
        next_due_date=timezone.localdate() + timedelta(days=2),  # inside the 72h window
    )

    assert remind_expiring_clients() == 1
    assert remind_expiring_clients() == 0  # same cycle -> silent

    client.refresh_from_db()
    assert client.expiry_reminded_on == client.next_due_date


def test_a_renewal_re_arms_the_reminder():
    operator = OperatorFactory(slug="rearm")
    PppoeSettings.objects.create(operator=operator, pre_expiry_reminder_hours=[72])
    client = PppoeClientFactory(
        operator=operator, status=Client.Status.ACTIVE, phone="254700000001",
        next_due_date=timezone.localdate() + timedelta(days=1),
    )
    remind_expiring_clients()

    # Renewal moves the due date forward.
    client.next_due_date = timezone.localdate() + timedelta(days=1)
    Client.objects.filter(pk=client.pk).update(
        next_due_date=timezone.localdate() + timedelta(days=31)
    )
    # ...but the new due date is outside the 72h window, so no reminder yet.
    assert remind_expiring_clients() == 0

    Client.objects.filter(pk=client.pk).update(
        next_due_date=timezone.localdate() + timedelta(days=2)
    )
    assert remind_expiring_clients() == 1  # re-armed for the new cycle


def test_reminders_are_off_by_default():
    operator = OperatorFactory(slug="noremind")
    PppoeClientFactory(
        operator=operator, status=Client.Status.ACTIVE, phone="254700000001",
        next_due_date=timezone.localdate() + timedelta(days=1),
    )
    assert remind_expiring_clients() == 0


# --- invoicing: auto-generate toggle + prefix -------------------------------------------


def test_auto_generate_off_skips_the_operator():
    operator = OperatorFactory(slug="manual")
    PppoeSettings.objects.create(operator=operator, auto_generate_invoices=False)
    PppoeClientFactory(
        operator=operator, status=Client.Status.ACTIVE,
        billing_day=timezone.localdate().day,
    )

    issue_due_invoices()

    assert Invoice.objects.filter(operator=operator).count() == 0


def test_auto_generate_on_by_default_issues_invoices():
    operator = OperatorFactory(slug="auto")
    PppoeClientFactory(
        operator=operator, status=Client.Status.ACTIVE,
        billing_day=timezone.localdate().day,
    )

    issue_due_invoices()

    assert Invoice.objects.filter(operator=operator).count() == 1


def test_the_invoice_prefix_is_used_in_the_number():
    operator = OperatorFactory(slug="prefix")
    PppoeSettings.objects.create(operator=operator, invoice_prefix="ACME")
    client = PppoeClientFactory(operator=operator, status=Client.Status.ACTIVE)

    inv = issue_invoice(client, timezone.localdate())

    assert inv.number.startswith("ACME-")


# --- the settings API -------------------------------------------------------------------


def test_the_api_round_trips_and_validates_choices():
    operator = OperatorFactory(slug="api")

    ok = owner(operator).patch(
        SETTINGS_URL,
        {"inactive_prune_days": 30, "pre_expiry_reminder_hours": [72, 24, 24],
         "invoice_prefix": "INV"},
        format="json",
    )
    assert ok.status_code == 200
    assert ok.json()["inactive_prune_days"] == 30
    assert ok.json()["pre_expiry_reminder_hours"] == [24, 72]  # deduped + sorted

    # A value outside the allow-list is refused, not silently stored.
    bad = owner(operator).patch(
        SETTINGS_URL, {"pre_expiry_reminder_hours": [999]}, format="json"
    )
    assert bad.status_code == 400

    bad_prefix = owner(operator).patch(
        SETTINGS_URL, {"invoice_prefix": "bad prefix!"}, format="json"
    )
    assert bad_prefix.status_code == 400


def test_never_prune_is_expressible():
    operator = OperatorFactory(slug="never")
    PppoeSettings.objects.create(operator=operator, inactive_prune_days=30)

    resp = owner(operator).patch(
        SETTINGS_URL, {"inactive_prune_days": None}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["inactive_prune_days"] is None
    operator.refresh_from_db()
    assert operator.pppoe_settings.inactive_prune_days is None


def test_fup_thresholds_save_and_metering_is_live():
    operator = OperatorFactory(slug="fup")

    resp = owner(operator).patch(
        SETTINGS_URL, {"fup_alert_percents": [80, 95]}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["fup_alert_percents"] == [80, 95]
    # Metering exists now (pppoe.metering), so FUP alerts fire for capped plans.
    assert resp.json()["fup_metering_ready"] is True
