"""Settings > Operator alerts: the settings API, router up/down alerts, PPPoE outage
compensation, and the daily sales digest."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.notifications.models import Message, OperatorAlertSettings
from apps.notifications.services import alert_settings_for
from apps.pppoe.models import Client
from apps.provisioning.models import Router, RouterOutage
from apps.provisioning.outages import (
    compensate_outage,
    on_router_offline,
    on_router_online,
)

from .factories import (
    OperatorFactory,
    PppoeClientFactory,
    RouterFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

ALERTS_URL = "/api/v1/notifications/settings/alerts/"


def staff(operator, role=Role.TENANT_OWNER):
    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=role))
    return c


def _enable(operator, **flags):
    """Turn on one or more operator-alert switches for an operator."""
    row = alert_settings_for(operator)
    for field, value in flags.items():
        setattr(row, field, value)
    row.save()
    return row


# --------------------------------------------------------------------------------------
# Settings API
# --------------------------------------------------------------------------------------


class TestSettingsApi:
    def test_get_returns_off_by_default(self):
        op = OperatorFactory()
        body = staff(op).get(ALERTS_URL).json()
        assert body == {
            "router_alerts_enabled": False,
            "router_alert_phones": [],
            "prefer_whatsapp": False,
            "compensate_outages": False,
            "sales_digest_enabled": False,
        }

    def test_patch_updates_flags(self):
        op = OperatorFactory()
        resp = staff(op).patch(
            ALERTS_URL,
            {"router_alerts_enabled": True, "compensate_outages": True,
             "sales_digest_enabled": True, "prefer_whatsapp": True},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        row = OperatorAlertSettings.objects.get(operator=op)
        assert row.router_alerts_enabled
        assert row.compensate_outages
        assert row.sales_digest_enabled
        assert row.prefer_whatsapp

    def test_patch_normalises_phone_numbers(self):
        op = OperatorFactory()
        resp = staff(op).patch(
            ALERTS_URL, {"router_alert_phones": ["0742531957", "0742531957", "254711000000"]},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        # 07... becomes 2547..., and the duplicate is collapsed.
        assert resp.json()["router_alert_phones"] == ["254742531957", "254711000000"]

    def test_patch_rejects_a_bad_number(self):
        op = OperatorFactory()
        resp = staff(op).patch(ALERTS_URL, {"router_alert_phones": ["not-a-phone"]}, format="json")
        assert resp.status_code == 400

    def test_patch_writes_an_audit_line(self):
        from apps.core.models import AuditLog

        op = OperatorFactory()
        staff(op).patch(ALERTS_URL, {"router_alerts_enabled": True}, format="json")
        assert AuditLog.objects.filter(operator=op, action="operator_alerts_updated").exists()

    def test_another_isp_cannot_read_mine(self):
        mine, theirs = OperatorFactory(slug="mine"), OperatorFactory(slug="theirs")
        alert_settings_for(mine)  # materialise mine's row
        # Their session, patching, only ever touches THEIR row.
        staff(theirs).patch(ALERTS_URL, {"router_alerts_enabled": True}, format="json")
        assert not OperatorAlertSettings.objects.get(operator=mine).router_alerts_enabled


# --------------------------------------------------------------------------------------
# Router status alerts
# --------------------------------------------------------------------------------------


def _online_router(op, **extra):
    return RouterFactory(operator=op, status=Router.Status.ONLINE, **extra)


class TestRouterAlerts:
    def test_offline_then_online_texts_the_team(self):
        op = OperatorFactory()
        conf = alert_settings_for(op)
        conf.router_alerts_enabled = True
        conf.router_alert_phones = ["254742531957"]
        conf.save()
        router = _online_router(op, name="Kibera A")

        on_router_offline(router)
        down = Message.objects.filter(operator=op, category=Message.Category.ALERT)
        assert down.count() == 1
        assert "OFFLINE" in down.first().body
        assert down.first().to_phone == "254742531957"

        on_router_online(router)
        up = Message.objects.filter(
            operator=op, category=Message.Category.ALERT, body__contains="BACK ONLINE"
        )
        assert up.count() == 1

    def test_nothing_is_sent_when_alerts_are_off(self):
        op = OperatorFactory()  # defaults: alerts off
        router = _online_router(op)
        on_router_offline(router)
        assert not Message.objects.filter(operator=op, category=Message.Category.ALERT).exists()

    def test_falls_back_to_admin_numbers_when_no_list_is_set(self):
        op = OperatorFactory()
        owner = UserFactory(operator=op, phone="254700111222", role=Role.TENANT_OWNER)
        conf = alert_settings_for(op)
        conf.router_alerts_enabled = True  # no explicit phones
        conf.save()
        on_router_offline(_online_router(op))
        assert Message.objects.filter(operator=op, to_phone=owner.phone).exists()

    def test_offline_opens_exactly_one_outage(self):
        op = OperatorFactory()
        router = _online_router(op)
        on_router_offline(router)
        on_router_offline(router)  # a second detection must not open a second window
        assert RouterOutage.objects.filter(router=router, ended_at__isnull=True).count() == 1


# --------------------------------------------------------------------------------------
# Outage compensation
# --------------------------------------------------------------------------------------


def _outage(router, *, minutes_down: int, ended=True):
    now = timezone.now()
    return RouterOutage.objects.create(
        router=router,
        started_at=now - timedelta(minutes=minutes_down),
        ended_at=now if ended else None,
    )


def _active_client(op, router, *, due_in_days=10):
    return PppoeClientFactory(
        operator=op, router=router, status=Client.Status.ACTIVE,
        next_due_date=timezone.localdate() + timedelta(days=due_in_days),
    )


class TestOutageCompensation:
    def test_short_outage_credits_nobody(self):
        op = OperatorFactory()
        _enable(op, compensate_outages=True)
        router = RouterFactory(operator=op)
        client = _active_client(op, router)
        credited = compensate_outage(_outage(router, minutes_down=5))
        assert credited == 0
        client.refresh_from_db()
        assert client.outage_credit_seconds == 0

    def test_sub_day_outage_banks_seconds_without_moving_the_date(self):
        op = OperatorFactory()
        _enable(op, compensate_outages=True)
        router = RouterFactory(operator=op)
        client = _active_client(op, router)
        due_before = client.next_due_date

        credited = compensate_outage(_outage(router, minutes_down=180))  # 3 hours
        assert credited == 1
        client.refresh_from_db()
        assert client.outage_credit_seconds == 180 * 60
        assert client.next_due_date == due_before  # under a day: no whole day rolled yet

    def test_accrued_seconds_roll_a_whole_day_onto_the_date(self):
        op = OperatorFactory()
        _enable(op, compensate_outages=True)
        router = RouterFactory(operator=op)
        client = _active_client(op, router)
        client.outage_credit_seconds = 82_800  # already banked 23h
        client.save()
        due_before = client.next_due_date

        compensate_outage(_outage(router, minutes_down=120))  # +2h -> crosses 24h once
        client.refresh_from_db()
        assert client.next_due_date == due_before + timedelta(days=1)
        assert client.outage_credit_seconds == 3600  # 25h banked - 24h rolled = 1h remainder

    def test_only_active_clients_are_credited(self):
        op = OperatorFactory()
        _enable(op, compensate_outages=True)
        router = RouterFactory(operator=op)
        active = _active_client(op, router)
        suspended = PppoeClientFactory(
            operator=op, router=router, status=Client.Status.SUSPENDED,
            next_due_date=timezone.localdate(),
        )
        credited = compensate_outage(_outage(router, minutes_down=60))
        assert credited == 1
        active.refresh_from_db()
        suspended.refresh_from_db()
        assert active.outage_credit_seconds == 3600
        assert suspended.outage_credit_seconds == 0

    def test_compensation_is_idempotent(self):
        op = OperatorFactory()
        _enable(op, compensate_outages=True)
        router = RouterFactory(operator=op)
        client = _active_client(op, router)
        outage = _outage(router, minutes_down=60)

        assert compensate_outage(outage) == 1
        assert compensate_outage(outage) == 0  # second run does nothing
        client.refresh_from_db()
        assert client.outage_credit_seconds == 3600  # not doubled

    def test_no_credit_when_the_toggle_is_off(self):
        op = OperatorFactory()  # compensate_outages defaults False
        router = RouterFactory(operator=op)
        client = _active_client(op, router)
        assert compensate_outage(_outage(router, minutes_down=120)) == 0
        client.refresh_from_db()
        assert client.outage_credit_seconds == 0

    def test_recovery_closes_the_outage_and_compensates(self):
        op = OperatorFactory()
        _enable(op, compensate_outages=True)
        router = RouterFactory(operator=op, status=Router.Status.ONLINE)
        client = _active_client(op, router)
        # A window opened 30 minutes ago and is still open.
        RouterOutage.objects.create(
            router=router, started_at=timezone.now() - timedelta(minutes=30),
        )
        on_router_online(router)
        outage = RouterOutage.objects.get(router=router)
        assert outage.ended_at is not None
        assert outage.compensated_at is not None
        client.refresh_from_db()
        assert client.outage_credit_seconds == pytest.approx(30 * 60, abs=5)


# --------------------------------------------------------------------------------------
# Sales digest
# --------------------------------------------------------------------------------------


def _sale_yesterday(op, amount):
    entry = LedgerEntry.objects.create(
        operator=op, entry_type=LedgerEntry.Type.SALE, amount=Decimal(amount)
    )
    yday = timezone.localdate() - timedelta(days=1)
    when = timezone.make_aware(datetime.combine(yday, time(12, 0)))
    LedgerEntry.objects.filter(pk=entry.pk).update(created_at=when)
    return entry


class TestSalesDigest:
    def test_emails_the_enabled_isp_yesterdays_takings(self, mailoutbox):
        from apps.notifications.tasks import send_sales_digests

        op = OperatorFactory(name="Blue ISP")
        UserFactory(operator=op, email="owner@blue.test", role=Role.TENANT_OWNER)
        _enable(op, sales_digest_enabled=True)
        _sale_yesterday(op, "1500")
        _sale_yesterday(op, "500")

        assert send_sales_digests() == 1
        assert len(mailoutbox) == 1
        mail = mailoutbox[0]
        assert "owner@blue.test" in mail.to
        assert "2,000" in mail.subject  # KES 2,000 gross
        assert "2 payments" in mail.body

    def test_no_email_when_the_digest_is_off(self, mailoutbox):
        from apps.notifications.tasks import send_sales_digests

        op = OperatorFactory()
        UserFactory(operator=op, email="owner@x.test", role=Role.TENANT_OWNER)
        _sale_yesterday(op, "1000")  # sales exist, but the digest is off
        assert send_sales_digests() == 0
        assert mailoutbox == []

    def test_quiet_day_still_sends_a_zero_digest(self, mailoutbox):
        from apps.notifications.tasks import send_sales_digests

        op = OperatorFactory()
        UserFactory(operator=op, email="owner@quiet.test", role=Role.TENANT_OWNER)
        _enable(op, sales_digest_enabled=True)
        assert send_sales_digests() == 1
        assert "No payments" in mailoutbox[0].body
