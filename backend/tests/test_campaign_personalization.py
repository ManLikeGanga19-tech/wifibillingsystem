"""Campaigns personalise the two broadcast-safe tokens (@first_name, @company_name) per recipient,
and leave every per-payment token exactly as typed (the composer flags those)."""

import pytest

from apps.notifications.models import Campaign, Message
from apps.notifications.services import personalize_campaign
from apps.notifications.tasks import dispatch_campaign

from .factories import OperatorFactory, SubscriberFactory

pytestmark = pytest.mark.django_db


class TestPersonalizeHelper:
    def test_fills_safe_tokens_and_leaves_per_payment_ones(self):
        out = personalize_campaign(
            "Hi @first_name from @company_name — @package_name expires @expiry_date",
            first_name="Jane",
            company_name="Acme WiFi",
        )
        assert out == "Hi Jane from Acme WiFi — @package_name expires @expiry_date"

    def test_missing_first_name_renders_empty(self):
        assert personalize_campaign("Hi @first_name!", first_name="", company_name="X") == "Hi !"


class TestDispatchPersonalises:
    def test_each_recipient_gets_their_own_name(self, monkeypatch):
        # Isolate the personalisation from the actual send path.
        monkeypatch.setattr("apps.notifications.tasks.send_message.delay", lambda pk: None)
        op = OperatorFactory(name="Blue ISP")
        SubscriberFactory(operator=op, name="Jane Doe", phone="254700000001")
        SubscriberFactory(operator=op, name="John Smith", phone="254700000002")

        campaign = Campaign.objects.create(
            operator=op, name="promo", channel="sms", audience="all",
            body="Hi @first_name from @company_name! @package_name",
        )
        dispatch_campaign(campaign.pk)

        bodies = set(Message.objects.filter(campaign=campaign).values_list("body", flat=True))
        # @first_name is per-recipient; @company_name is the ISP; @package_name is left as typed.
        assert bodies == {
            "Hi Jane from Blue ISP! @package_name",
            "Hi John from Blue ISP! @package_name",
        }
