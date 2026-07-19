"""The PPPoE (fixed-line) customer SMS that fire on lifecycle events:

  * welcome + login details on FIRST activation (provision_client), and
  * "your line is suspended — pay to reconnect" on suspension (suspend_client).

These two had no coverage. The sibling fixed-line/hotspot messages are covered elsewhere: the
hotspot receipt + expiry warning in test_sms_notifications, the hotspot data warning in
test_data_caps, the PPPoE FUP alert in test_pppoe_metering, and the PPPoE renewal reminder in
test_pppoe_lifecycle.

We assert on the ACTUAL delivery (DummyProvider.sent), i.e. the message that reaches the customer
after the send-on-commit chain runs — not on the notify_* function in isolation — so the whole
event -> template -> gateway wiring is proven.
"""

import pytest

from apps.notifications.providers.dummy import DummyProvider
from apps.pppoe.models import Client
from apps.pppoe.services import create_client, provision_client, suspend_client

from .factories import OperatorFactory, PppoeClientFactory, RouterFactory, ServicePlanFactory

pytestmark = pytest.mark.django_db

PHONE = "254700111222"


def _texts(phone=PHONE):
    """Bodies actually delivered to `phone` (DummyProvider.sent is reset per test by conftest)."""
    return [body for to, body in DummyProvider.sent if to == phone]


def _new_client(operator, *, phone=PHONE, **extra):
    """A brand-new (PENDING_INSTALL) fixed-line client, ready for its first provisioning."""
    router = RouterFactory(operator=operator)
    plan = ServicePlanFactory(operator=operator)
    return create_client(
        operator=operator, plan=plan, router=router, full_name="Jane Doe", phone=phone, **extra
    )


class TestWelcomeOnFirstActivation:
    def test_first_activation_texts_the_login_details(self, django_capture_on_commit_callbacks):
        client = _new_client(OperatorFactory())
        with django_capture_on_commit_callbacks(execute=True):
            provision_client(client)
        sent = _texts()
        assert len(sent) == 1
        # The welcome carries the credentials the customer needs to connect.
        assert client.pppoe_username in sent[0]

    def test_re_provisioning_does_not_welcome_again(self, django_capture_on_commit_callbacks):
        client = _new_client(OperatorFactory())
        with django_capture_on_commit_callbacks(execute=True):
            provision_client(client)  # first activation -> welcome
            provision_client(client)  # already active -> silent
        assert len(_texts()) == 1

    def test_the_customer_sms_off_switch_is_respected(self, django_capture_on_commit_callbacks):
        client = _new_client(OperatorFactory(notify_customers_sms=False))
        with django_capture_on_commit_callbacks(execute=True):
            provision_client(client)
        assert _texts() == []

    def test_a_client_with_no_phone_is_not_texted(self, django_capture_on_commit_callbacks):
        client = _new_client(OperatorFactory(), phone="")
        with django_capture_on_commit_callbacks(execute=True):
            provision_client(client)
        assert DummyProvider.sent == []


class TestSuspensionSms:
    def test_suspending_texts_pay_to_reconnect(self, django_capture_on_commit_callbacks):
        client = PppoeClientFactory(status=Client.Status.ACTIVE, phone=PHONE)
        with django_capture_on_commit_callbacks(execute=True):
            suspend_client(client)
        sent = _texts()
        assert len(sent) == 1
        assert "reconnect" in sent[0].lower() or "expired" in sent[0].lower()

    def test_the_customer_sms_off_switch_is_respected(self, django_capture_on_commit_callbacks):
        op = OperatorFactory(notify_customers_sms=False)
        client = PppoeClientFactory(operator=op, status=Client.Status.ACTIVE, phone=PHONE)
        with django_capture_on_commit_callbacks(execute=True):
            suspend_client(client)
        assert _texts() == []

    def test_a_client_with_no_phone_is_not_texted(self, django_capture_on_commit_callbacks):
        client = PppoeClientFactory(status=Client.Status.ACTIVE, phone="")
        with django_capture_on_commit_callbacks(execute=True):
            suspend_client(client)
        assert DummyProvider.sent == []

    def test_a_non_serviceable_client_is_never_suspended_or_texted(
        self, django_capture_on_commit_callbacks
    ):
        # PENDING_INSTALL isn't a live line, so suspend_client no-ops (and sends nothing).
        client = PppoeClientFactory(status=Client.Status.PENDING_INSTALL, phone=PHONE)
        with django_capture_on_commit_callbacks(execute=True):
            suspend_client(client)
        assert _texts() == []
        client.refresh_from_db()
        assert client.status == Client.Status.PENDING_INSTALL
