"""Communications settings: the hybrid gateway rule, and the secrets that must not leak.

The two things worth breaking a build over:
  * an ISP's own credentials are used when they configured them, and the platform's
    otherwise — because a message sent on the wrong account is billed to the wrong party;
  * a credential, once saved, is never readable back through the API — because an SMS key
    is money, and a leaked one is spent at the ISP's cost.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.notifications.models import Channel, MessagingSettings
from apps.notifications.providers import (
    AfricasTalkingSMS,
    DjangoEmailProvider,
    ProviderError,
    SmtpEmailProvider,
    WhatsAppCloud,
    resolve_provider,
)

from .factories import OperatorFactory, UserFactory

pytestmark = pytest.mark.django_db

SETTINGS_URL = "/api/v1/notifications/settings/"
TEST_URL = "/api/v1/notifications/settings/test/"


def owner(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER)
    )
    return c


def support(operator):
    c = APIClient()
    c.force_authenticate(
        user=UserFactory(operator=operator, is_staff=True, role=Role.PLATFORM_SUPPORT)
    )
    return c


# --- the hybrid rule ------------------------------------------------------------------


def test_sms_falls_back_to_the_platform_when_the_isp_has_no_own_account(settings):
    """The day-one case: an ISP who never opens this page still sends SMS."""
    settings.AT_USERNAME = "platform-user"
    settings.AT_API_KEY = "platform-key"
    settings.AT_SENDER_ID = "WIFIOS"
    operator = OperatorFactory(slug="isp-default")
    MessagingSettings.objects.create(operator=operator)  # all defaults = platform

    provider = resolve_provider(Channel.SMS, operator)

    assert isinstance(provider, AfricasTalkingSMS)
    assert provider.api_key == "platform-key"
    assert provider.sender_id == "WIFIOS"


def test_sms_uses_the_isps_own_account_once_they_configure_one(settings):
    settings.AT_API_KEY = "platform-key"
    operator = OperatorFactory(slug="isp-own-sms")
    MessagingSettings.objects.create(
        operator=operator,
        sms_mode=MessagingSettings.Mode.OWN,
        sms_username="acme",
        sms_api_key="acme-secret-key",
        sms_sender_id="ACME",
    )

    provider = resolve_provider(Channel.SMS, operator)

    assert provider.api_key == "acme-secret-key"
    assert provider.username == "acme"
    assert provider.sender_id == "ACME"


def test_own_mode_with_a_missing_key_falls_back_instead_of_going_silent(settings):
    """A half-configured channel must not black-hole customer notifications: the ISP
    said 'own' but saved no key, so their customers still get told they're online."""
    settings.AT_API_KEY = "platform-key"
    operator = OperatorFactory(slug="isp-half")
    MessagingSettings.objects.create(
        operator=operator, sms_mode=MessagingSettings.Mode.OWN, sms_username="acme"
    )

    provider = resolve_provider(Channel.SMS, operator)

    assert provider.api_key == "platform-key"


def test_email_uses_the_isps_own_smtp_when_configured():
    operator = OperatorFactory(slug="isp-own-smtp")
    MessagingSettings.objects.create(
        operator=operator,
        email_mode=MessagingSettings.Mode.OWN,
        smtp_host="mail.acme.co.ke",
        smtp_username="postmaster",
        smtp_password="smtp-secret",
        from_email="billing@acme.co.ke",
        from_name="Acme WiFi",
    )

    provider = resolve_provider(Channel.EMAIL, operator)

    assert isinstance(provider, SmtpEmailProvider)
    assert provider.host == "mail.acme.co.ke"
    assert provider.sender == '"Acme WiFi" <billing@acme.co.ke>'


def test_email_defaults_to_the_platform_mailer():
    operator = OperatorFactory(slug="isp-platform-mail")
    MessagingSettings.objects.create(operator=operator)

    assert isinstance(resolve_provider(Channel.EMAIL, operator), DjangoEmailProvider)


def test_whatsapp_is_off_until_the_isp_brings_their_own_account():
    """We hold no Meta business identity for them — say so loudly rather than pretend."""
    operator = OperatorFactory(slug="isp-no-wa")
    MessagingSettings.objects.create(operator=operator)

    with pytest.raises(ProviderError, match="switched off"):
        resolve_provider(Channel.WHATSAPP, operator)


def test_whatsapp_uses_the_isps_own_account_when_configured():
    operator = OperatorFactory(slug="isp-own-wa")
    MessagingSettings.objects.create(
        operator=operator,
        whatsapp_mode=MessagingSettings.Mode.OWN,
        whatsapp_phone_number_id="123456",
        whatsapp_token="wa-secret",
    )

    provider = resolve_provider(Channel.WHATSAPP, operator)

    assert isinstance(provider, WhatsAppCloud)
    assert provider.token == "wa-secret"


# --- secrets ---------------------------------------------------------------------------


def test_the_api_never_hands_back_a_saved_credential():
    """The whole point: a read reports that a key EXISTS, never what it is. If this ever
    regresses, an ISP's SMS credit is spendable by anyone who can read the response."""
    operator = OperatorFactory(slug="isp-secrets")
    isp_client = owner(operator)
    MessagingSettings.objects.create(
        operator=operator,
        sms_mode=MessagingSettings.Mode.OWN,
        sms_username="acme",
        sms_api_key="super-secret-key",
        smtp_password="smtp-secret",
        whatsapp_token="wa-secret",
    )

    resp = isp_client.get(SETTINGS_URL)

    assert resp.status_code == 200
    assert resp.json()["sms_api_key_configured"] is True
    body = resp.content.decode()
    for secret in ("super-secret-key", "smtp-secret", "wa-secret"):
        assert secret not in body


def test_a_blank_secret_on_save_keeps_the_existing_one():
    """The console cannot show the key back, so it submits it blank — that must not wipe
    a working gateway."""
    operator = OperatorFactory(slug="isp-blank")
    isp_client = owner(operator)
    MessagingSettings.objects.create(
        operator=operator,
        sms_mode=MessagingSettings.Mode.OWN,
        sms_username="acme",
        sms_api_key="keep-me",
    )

    resp = isp_client.patch(
        SETTINGS_URL,
        {"sms_mode": "own", "sms_username": "acme", "sms_api_key": "", "sms_sender_id": "ACME"},
        format="json",
    )

    assert resp.status_code == 200
    config = MessagingSettings.objects.get(operator=operator)
    assert config.sms_api_key == "keep-me"
    assert config.sms_sender_id == "ACME"


def test_a_credential_is_encrypted_at_rest():
    """Fernet at the column: whoever gets a database dump does not get the ISP's key."""
    from django.db import connection

    operator = OperatorFactory(slug="isp-encrypted")

    MessagingSettings.objects.create(
        operator=operator, sms_mode=MessagingSettings.Mode.OWN, sms_api_key="plaintext-key"
    )
    with connection.cursor() as cur:
        cur.execute(
            "SELECT sms_api_key FROM notifications_messagingsettings WHERE operator_id = %s",
            [operator.pk],
        )
        stored = cur.fetchone()[0]

    assert stored != "plaintext-key"
    assert "plaintext-key" not in stored


# --- guard rails -----------------------------------------------------------------------


def test_switching_to_own_without_a_key_is_refused():
    operator = OperatorFactory(slug='isp-nokey')
    isp_client = owner(operator)
    resp = isp_client.patch(
        SETTINGS_URL, {"sms_mode": "own", "sms_username": "acme"}, format="json"
    )

    assert resp.status_code == 400
    assert "sms_api_key" in resp.json()


def test_switching_to_own_is_allowed_when_the_key_was_saved_earlier():
    operator = OperatorFactory(slug='isp-saved')
    isp_client = owner(operator)
    MessagingSettings.objects.create(operator=operator, sms_api_key="saved-earlier",
                                     sms_username="acme")

    resp = isp_client.patch(SETTINGS_URL, {"sms_mode": "own"}, format="json")

    assert resp.status_code == 200
    assert MessagingSettings.objects.get(operator=operator).sms_mode == "own"


def test_one_isp_cannot_read_anothers_gateway():
    operator = OperatorFactory(slug='isp-mine')
    isp_client = owner(operator)
    other = OperatorFactory(slug="somebody-else")
    MessagingSettings.objects.create(
        operator=other, sms_mode=MessagingSettings.Mode.OWN, sms_api_key="their-key",
        sms_username="them", sms_sender_id="THEM",
    )

    resp = isp_client.get(SETTINGS_URL)

    assert resp.status_code == 200
    # We get OUR row (freshly defaulted), never theirs.
    assert resp.json()["sms_sender_id"] == ""
    assert resp.json()["sms_api_key_configured"] is False
    assert "their-key" not in resp.content.decode()


def test_read_only_support_cannot_change_the_gateway():
    support_client = support(OperatorFactory(slug='isp-support'))
    resp = support_client.patch(SETTINGS_URL, {"sms_mode": "platform"}, format="json")

    assert resp.status_code == 403
