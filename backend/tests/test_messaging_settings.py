"""Communications: the gateway registry, the credits that pay for the managed one, and
the secrets that must never leak.

The things worth breaking a build over:
  * messages leave on the gateway the ISP actually chose — a message sent on the wrong
    account is billed to the wrong party;
  * a credential, once saved, is never readable back through the API — a bulk-SMS key is
    money, and a leaked one is spent at the ISP's cost;
  * credits are never charged twice for one message, and never spent below zero.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.billing.models import LedgerEntry
from apps.billing.services import WalletError
from apps.notifications import credits
from apps.notifications.models import (
    Channel,
    MessagingSettings,
    ProviderCredential,
    SmsCreditEntry,
)
from apps.notifications.providers import (
    AfricasTalkingSMS,
    ProviderError,
    is_managed_sms,
    resolve_provider,
)
from apps.notifications.providers.bulk import MobileSasaSMS, TwilioSMS

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

SMS_URL = "/api/v1/notifications/settings/sms/"
WA_URL = "/api/v1/notifications/settings/whatsapp/"
BUY_URL = "/api/v1/notifications/settings/credits/buy/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def fund_wallet(operator, amount="10000.00"):
    LedgerEntry.objects.create(
        operator=operator, entry_type=LedgerEntry.Type.SALE, amount=Decimal(amount)
    )


def spend_welcome_credits(operator):
    """Every operator is born with WELCOME_CREDITS (see signals). Tests about an EMPTY
    balance have to actually empty it."""
    SmsCreditEntry.objects.filter(operator=operator).delete()


# --- which gateway sends ----------------------------------------------------------------


def test_a_new_isp_starts_with_credits_so_the_first_receipt_sends():
    """The managed gateway promises it works on day one. A zero balance would make that
    a lie — the first customer would pay and hear nothing back."""
    operator = OperatorFactory(slug="isp-newborn")

    assert credits.balance(operator) == credits.WELCOME_CREDITS


def test_sms_defaults_to_the_managed_wifios_gateway(settings):
    """Day one: an ISP who never opens this page still sends SMS, on our account."""
    settings.AT_USERNAME = "platform-user"
    settings.AT_API_KEY = "platform-key"
    operator = OperatorFactory(slug="isp-default")
    MessagingSettings.objects.create(operator=operator)

    provider = resolve_provider(Channel.SMS, operator)

    assert isinstance(provider, AfricasTalkingSMS)
    assert provider.api_key == "platform-key"
    assert is_managed_sms(operator) is True


def test_sms_leaves_on_the_isps_own_provider_once_they_activate_one():
    operator = OperatorFactory(slug="isp-own-sms")
    config = MessagingSettings.objects.create(operator=operator, sms_provider="mobilesasa")
    row = ProviderCredential(operator=operator, channel=Channel.SMS, provider="mobilesasa")
    row.values = {"api_token": "their-token", "sender_id": "ACME"}
    row.save()

    provider = resolve_provider(Channel.SMS, operator)

    assert isinstance(provider, MobileSasaSMS)
    assert provider.token == "their-token"
    # Their gateway, their bill — we do not meter credits for it.
    assert is_managed_sms(operator) is False
    assert config.uses_own(Channel.SMS) is True


def test_whatsapp_is_silent_until_a_provider_is_connected():
    """We hold no Meta identity for them — say so, rather than pretend to send."""
    operator = OperatorFactory(slug="isp-no-wa")
    MessagingSettings.objects.create(operator=operator)

    with pytest.raises(ProviderError, match="not connected"):
        resolve_provider(Channel.WHATSAPP, operator)


def test_whatsapp_uses_the_connected_provider():
    operator = OperatorFactory(slug="isp-wa")
    MessagingSettings.objects.create(operator=operator, whatsapp_provider="twilio")
    row = ProviderCredential(operator=operator, channel=Channel.WHATSAPP, provider="twilio")
    row.values = {"account_sid": "AC1", "auth_token": "tok", "from_number": "+1555"}
    row.save()

    provider = resolve_provider(Channel.WHATSAPP, operator)

    assert isinstance(provider, TwilioSMS)
    assert provider.whatsapp is True


# --- secrets -----------------------------------------------------------------------------


def test_the_api_never_hands_back_a_saved_credential():
    """A read says a key EXISTS, never what it is. If this regresses, an ISP's SMS credit
    is spendable by anyone who can read the response."""
    operator = OperatorFactory(slug="isp-secrets")
    row = ProviderCredential(operator=operator, channel=Channel.SMS, provider="mobilesasa")
    row.values = {"api_token": "super-secret-token", "sender_id": "ACME"}
    row.save()

    resp = owner(operator).get(SMS_URL)

    assert resp.status_code == 200
    assert "super-secret-token" not in resp.content.decode()
    card = next(p for p in resp.json()["providers"] if p["id"] == "mobilesasa")
    token_field = next(f for f in card["fields"] if f["key"] == "api_token")
    assert token_field["set"] is True
    assert token_field["value"] == ""  # secrets are never echoed
    # A non-secret field IS echoed, so the form is editable.
    assert next(f for f in card["fields"] if f["key"] == "sender_id")["value"] == "ACME"


def test_a_blank_secret_on_save_keeps_the_existing_one():
    operator = OperatorFactory(slug="isp-blank")
    row = ProviderCredential(operator=operator, channel=Channel.SMS, provider="mobilesasa")
    row.values = {"api_token": "keep-me", "sender_id": "OLD"}
    row.save()

    resp = owner(operator).post(
        f"{SMS_URL}mobilesasa/",
        {"credentials": {"api_token": "", "sender_id": "NEW"}},
        format="json",
    )

    assert resp.status_code == 200
    stored = ProviderCredential.objects.get(operator=operator, provider="mobilesasa").values
    assert stored["api_token"] == "keep-me"
    assert stored["sender_id"] == "NEW"


def test_credentials_are_encrypted_at_rest():
    """Whoever gets a database dump does not get the ISP's key."""
    from django.db import connection

    operator = OperatorFactory(slug="isp-encrypted")
    row = ProviderCredential(operator=operator, channel=Channel.SMS, provider="mobilesasa")
    row.values = {"api_token": "plaintext-token", "sender_id": "ACME"}
    row.save()

    with connection.cursor() as cur:
        cur.execute(
            "SELECT secrets FROM notifications_providercredential WHERE id = %s", [row.pk]
        )
        stored = cur.fetchone()[0]

    assert "plaintext-token" not in stored


def test_one_isp_cannot_see_anothers_gateway():
    other = OperatorFactory(slug="somebody-else")
    row = ProviderCredential(operator=other, channel=Channel.SMS, provider="mobilesasa")
    row.values = {"api_token": "their-token", "sender_id": "THEM"}
    row.save()

    operator = OperatorFactory(slug="isp-mine")
    resp = owner(operator).get(SMS_URL)

    assert resp.status_code == 200
    assert "their-token" not in resp.content.decode()
    card = next(p for p in resp.json()["providers"] if p["id"] == "mobilesasa")
    assert card["configured"] is False


# --- guard rails --------------------------------------------------------------------------


def test_activating_a_half_configured_gateway_is_refused():
    """Activating a gateway with no key would silently stop every receipt the ISP sends."""
    operator = OperatorFactory(slug="isp-half")

    resp = owner(operator).post(f"{SMS_URL}mobilesasa/activate/", {}, format="json")

    assert resp.status_code == 400
    # Nothing was switched: they are still on the gateway that actually works.
    assert not MessagingSettings.objects.filter(
        operator=operator, sms_provider="mobilesasa"
    ).exists()


def test_configuring_without_a_required_field_is_refused():
    operator = OperatorFactory(slug="isp-missing")

    resp = owner(operator).post(
        f"{SMS_URL}mobilesasa/", {"credentials": {"sender_id": "ACME"}}, format="json"
    )

    assert resp.status_code == 400


def test_the_managed_gateway_takes_no_credentials():
    operator = OperatorFactory(slug="isp-managed")

    resp = owner(operator).post(
        f"{SMS_URL}wifios/", {"credentials": {"api_key": "nope"}}, format="json"
    )

    assert resp.status_code == 400


def test_disconnecting_sms_falls_back_to_the_managed_gateway():
    """SMS always has somewhere to land — an ISP who removes their key keeps sending."""
    operator = OperatorFactory(slug="isp-disconnect")
    MessagingSettings.objects.create(operator=operator, sms_provider="mobilesasa")
    row = ProviderCredential(operator=operator, channel=Channel.SMS, provider="mobilesasa")
    row.values = {"api_token": "t", "sender_id": "S"}
    row.save()

    resp = owner(operator).delete(f"{SMS_URL}mobilesasa/disconnect/")

    assert resp.status_code == 200
    assert MessagingSettings.objects.get(operator=operator).sms_provider == "wifios"
    assert not ProviderCredential.objects.filter(operator=operator).exists()


# --- credits ------------------------------------------------------------------------------


def test_buying_credits_moves_money_out_of_the_wallet():
    operator = OperatorFactory(slug="isp-buy")
    fund_wallet(operator, "10000.00")
    bundle = credits.bundle("growth")  # 5,000 SMS for KES 3,750

    credits.purchase(operator=operator, bundle_id="growth", user=None)

    assert credits.balance(operator) == credits.WELCOME_CREDITS + bundle.credits
    debit = LedgerEntry.objects.get(operator=operator, entry_type=LedgerEntry.Type.SMS_CREDITS)
    assert debit.amount == -bundle.price


def test_you_cannot_buy_credits_you_cannot_afford():
    """No overdraft: the ISP is never handed SMS they have not paid for."""
    operator = OperatorFactory(slug="isp-broke")
    fund_wallet(operator, "100.00")

    with pytest.raises(WalletError, match="wallet"):
        credits.purchase(operator=operator, bundle_id="growth", user=None)

    assert credits.balance(operator) == credits.WELCOME_CREDITS  # unchanged
    assert not LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.SMS_CREDITS).exists()


def test_a_send_is_charged_once_however_many_times_the_task_retries():
    """The debit is unique per message — a retried Celery task cannot rob an ISP twice."""
    from apps.notifications.models import Message

    operator = OperatorFactory(slug="isp-retry")
    fund_wallet(operator)
    credits.purchase(operator=operator, bundle_id="starter", user=None)
    msg = Message.objects.create(operator=operator, to_phone="254700000001", body="hi")

    credits.consume(operator, msg)
    credits.consume(operator, msg)  # the retry
    credits.consume(operator, msg)

    assert SmsCreditEntry.objects.filter(message=msg).count() == 1
    assert credits.balance(operator) == credits.WELCOME_CREDITS + 1_000 - 1


def test_a_long_message_costs_more_than_one_credit():
    """SMS is billed per 160-character segment; the gateway charges us for each."""
    from apps.notifications.tasks import _segments

    assert _segments("short") == 1
    assert _segments("x" * 160) == 1
    assert _segments("x" * 161) == 2
    assert _segments("x" * 306) == 2
    assert _segments("x" * 307) == 3


def test_an_isp_with_no_credits_does_not_send_on_the_managed_gateway():
    """We would be handing the gateway money the ISP never gave us."""
    from apps.notifications.models import Message
    from apps.notifications.tasks import send_message

    operator = OperatorFactory(slug="isp-empty")
    MessagingSettings.objects.create(operator=operator)  # managed
    spend_welcome_credits(operator)
    msg = Message.objects.create(operator=operator, to_phone="254700000002", body="hi")

    send_message(msg.pk)

    msg.refresh_from_db()
    assert msg.status == Message.Status.FAILED
    assert "credits" in msg.error.lower()


def test_an_isp_on_their_own_gateway_needs_no_credits():
    """Their provider bills them directly; metering them too would charge twice."""
    operator = OperatorFactory(slug="isp-byo")
    MessagingSettings.objects.create(operator=operator, sms_provider="mobilesasa")
    spend_welcome_credits(operator)

    assert is_managed_sms(operator) is False
    assert credits.balance(operator) == 0  # and that is fine — their provider bills them


def test_buying_credits_requires_the_second_factor():
    """Wallet money leaving is money leaving — same lock as a payout."""
    operator = OperatorFactory(slug="isp-mfa")
    fund_wallet(operator)

    resp = owner(operator).post(BUY_URL, {"bundle": "starter"}, format="json")

    assert resp.status_code == 403
    assert resp.json()["mfa_required"] is True
    assert credits.balance(operator) == credits.WELCOME_CREDITS  # nothing was bought
