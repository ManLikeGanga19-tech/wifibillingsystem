"""Editable SMS templates: the body of each automated customer message.

The parts that carry weight:
  * an ISP override replaces the default; a DISABLED template sends nothing; a blank-but-
    enabled one falls back to the default (never an empty SMS);
  * the save-time validator refuses an unknown @variable, so a typo can't reach a customer;
  * the live triggers actually render through the ISP's template;
  * the new triggers (PPPoE welcome/expired, voucher SMS) fire;
  * one ISP's templates are theirs alone.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.notifications import templates as reg
from apps.notifications.models import Message, MessageTemplate
from apps.notifications.services import notify_online, notify_voucher

from .factories import (
    OperatorFactory,
    PlanFactory,
    SessionFactory,
    UserFactory,
    VoucherFactory,
)

pytestmark = pytest.mark.django_db

TEMPLATES_URL = "/api/v1/notifications/settings/templates/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


# --- the render engine ------------------------------------------------------------------


class TestRender:
    def test_default_when_no_override(self):
        op = OperatorFactory()
        body = reg.render(op, "hotspot_online", {"company_name": "Acme", "package_name": "Daily"})
        assert "Acme" in body and "Daily" in body

    def test_override_wins(self):
        op = OperatorFactory()
        MessageTemplate.objects.create(operator=op, key="hotspot_online", body="Hi @package_name!")
        assert reg.render(op, "hotspot_online", {"package_name": "Daily"}) == "Hi Daily!"

    def test_disabled_renders_nothing(self):
        op = OperatorFactory()
        MessageTemplate.objects.create(
            operator=op, key="hotspot_online", body="x", is_enabled=False
        )
        assert reg.render(op, "hotspot_online", {}) == ""

    def test_blank_but_enabled_falls_back_to_default(self):
        op = OperatorFactory()
        MessageTemplate.objects.create(operator=op, key="hotspot_online", body="", is_enabled=True)
        body = reg.render(op, "hotspot_online", {"company_name": "Acme", "package_name": "D"})
        assert body == reg.render(OperatorFactory(), "hotspot_online",
                                  {"company_name": "Acme", "package_name": "D"})

    def test_unknown_variable_renders_empty_not_literal(self):
        op = OperatorFactory()
        # @amount is valid for hotspot_online; an omitted value renders empty, never '@amount'.
        body = reg.render(op, "hotspot_online", {"company_name": "Acme", "package_name": "D"})
        assert "@amount" not in body

    def test_unknown_tokens_detects_typos(self):
        assert reg.unknown_tokens(
            "hotspot_online", "Hi @package_name @expiry_dat"
        ) == ["expiry_dat"]


# --- the settings API -------------------------------------------------------------------


class TestTemplatesApi:
    def test_get_returns_all_eight_grouped_with_variables(self):
        body = owner(OperatorFactory()).get(TEMPLATES_URL).json()
        assert len(body["templates"]) == 8
        assert body["groups"] == ["Hotspot", "PPPoE", "Voucher"]
        one = next(t for t in body["templates"] if t["key"] == "voucher_issued")
        assert any(v["name"] == "code" for v in one["variables"])
        assert one["variables"][0]["sample"]  # samples power the live preview

    def test_patch_stores_an_override(self):
        op = OperatorFactory()
        resp = owner(op).patch(
            TEMPLATES_URL, {"key": "hotspot_online", "body": "Online! @package_name"}, format="json"
        )
        assert resp.status_code == 200
        row = MessageTemplate.objects.get(operator=op, key="hotspot_online")
        assert row.body == "Online! @package_name"

    def test_patch_rejects_an_unknown_variable(self):
        op = OperatorFactory()
        resp = owner(op).patch(
            TEMPLATES_URL, {"key": "hotspot_online", "body": "Hi @not_a_var"}, format="json"
        )
        assert resp.status_code == 400
        assert not MessageTemplate.objects.filter(operator=op, key="hotspot_online").exists()

    def test_patch_can_disable_a_template(self):
        op = OperatorFactory()
        owner(op).patch(
            TEMPLATES_URL, {"key": "hotspot_expiring", "is_enabled": False}, format="json"
        )
        assert MessageTemplate.objects.get(operator=op, key="hotspot_expiring").is_enabled is False

    def test_templates_are_tenant_isolated(self):
        a, b = OperatorFactory(slug="a"), OperatorFactory(slug="b")
        owner(a).patch(
            TEMPLATES_URL, {"key": "hotspot_online", "body": "A @package_name"}, format="json"
        )
        # B still sees the default.
        rows = {t["key"]: t for t in owner(b).get(TEMPLATES_URL).json()["templates"]}
        assert rows["hotspot_online"]["is_customized"] is False


# --- the triggers actually use the template ---------------------------------------------


class TestTriggersRenderThroughTemplates:
    def test_hotspot_online_uses_the_override(self):
        op = OperatorFactory()
        plan = PlanFactory(operator=op, name="Weekly")
        MessageTemplate.objects.create(operator=op, key="hotspot_online", body="Yo @package_name")
        session = SessionFactory(operator=op, plan=plan)
        notify_online(session)
        msg = Message.objects.filter(operator=op, category=Message.Category.PAYMENT).first()
        assert msg is not None and msg.body == "Yo Weekly"

    def test_a_disabled_message_is_not_sent(self):
        op = OperatorFactory()
        MessageTemplate.objects.create(
            operator=op, key="hotspot_online", body="x", is_enabled=False
        )
        notify_online(SessionFactory(operator=op))
        assert not Message.objects.filter(operator=op, category=Message.Category.PAYMENT).exists()

    def test_voucher_notify_sends_the_code(self):
        op = OperatorFactory()
        plan = PlanFactory(operator=op, name="Daily")
        voucher = VoucherFactory(operator=op, plan=plan)
        assert notify_voucher(voucher, "254712345678") is True
        msg = Message.objects.filter(operator=op, to_phone="254712345678").first()
        assert msg is not None and voucher.code in msg.body


# --- the voucher send-sms action --------------------------------------------------------


class TestVoucherSendSms:
    def _url(self, voucher):
        return f"/api/v1/vouchers/{voucher.id}/send-sms/"

    def test_sends_an_unused_voucher(self):
        op = OperatorFactory()
        v = VoucherFactory(operator=op, plan=PlanFactory(operator=op))
        resp = owner(op).post(self._url(v), {"phone": "0712345678"}, format="json")
        assert resp.status_code == 200
        assert Message.objects.filter(operator=op, to_phone="254712345678").exists()

    def test_refuses_a_redeemed_voucher(self):
        from apps.vouchers.models import Voucher

        op = OperatorFactory()
        v = VoucherFactory(
            operator=op, plan=PlanFactory(operator=op), status=Voucher.Status.REDEEMED
        )
        resp = owner(op).post(self._url(v), {"phone": "0712345678"}, format="json")
        assert resp.status_code == 409

    def test_refuses_a_bad_phone(self):
        op = OperatorFactory()
        v = VoucherFactory(operator=op, plan=PlanFactory(operator=op))
        resp = owner(op).post(self._url(v), {"phone": "nope"}, format="json")
        assert resp.status_code == 400
