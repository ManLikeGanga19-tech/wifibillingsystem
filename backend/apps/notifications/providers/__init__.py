"""Choosing WHOSE gateway a message leaves on.

The rule, in one place:

  1. Dev/test override (NOTIFICATIONS_PROVIDER=dummy) — nothing paid ever leaves the box.
  2. The provider the ISP has made ACTIVE for that channel, built from the credentials
     they stored for it.
  3. For SMS only, the default: the managed WIFI.OS gateway, which runs on our account
     and is metered in credits.

WhatsApp has no default. We hold no Meta business identity for an ISP, so an ISP who has
not connected a provider gets an explicit "not connected" rather than a silent black hole.
"""

import os

from ..catalog import MANAGED_SMS
from .africastalking import AfricasTalkingSMS
from .base import MessageProvider, ProviderError, SendResult
from .bulk import (
    ApiwapWhatsApp,
    BlessedTextsSMS,
    BongaSMS,
    HostPinnacleSMS,
    InfobipSMS,
    MobileSasaSMS,
    NotivaWhatsApp,
    TwilioSMS,
)
from .dummy import DummyProvider
from .email import DjangoEmailProvider, SmtpEmailProvider

SMS = "sms"
EMAIL = "email"
WHATSAPP = "whatsapp"

#: provider id -> how to build it from the ISP's stored credentials.
SMS_ADAPTERS = {
    "africastalking": lambda c: AfricasTalkingSMS(
        username=c.get("username", ""),
        api_key=c.get("api_key", ""),
        sender_id=c.get("sender_id", ""),
    ),
    "mobilesasa": lambda c: MobileSasaSMS(**c),
    "bongasms": lambda c: BongaSMS(**c),
    "blessedtexts": lambda c: BlessedTextsSMS(**c),
    "hostpinnacle": lambda c: HostPinnacleSMS(**c),
    "twilio": lambda c: TwilioSMS(**c),
    "infobip": lambda c: InfobipSMS(**c),
}

WHATSAPP_ADAPTERS = {
    "apiwap": lambda c: ApiwapWhatsApp(**c),
    "notiva": lambda c: NotivaWhatsApp(**c),
    "twilio": lambda c: TwilioSMS(whatsapp=True, **c),
    "infobip": lambda c: InfobipSMS(whatsapp=True, **c),
}


def _messaging_settings(operator):
    if operator is None:
        return None
    from ..models import MessagingSettings

    return MessagingSettings.objects.filter(operator=operator).first()


def _credentials(operator, channel: str, provider_id: str) -> dict:
    from ..models import ProviderCredential

    row = ProviderCredential.objects.filter(
        operator=operator, channel=channel, provider=provider_id
    ).first()
    return row.values if row else {}


def is_managed_sms(operator) -> bool:
    """True when this ISP's SMS leaves on OUR gateway — the only case we meter credits
    for. An ISP on their own provider is billed by that provider, not by us."""
    config = _messaging_settings(operator)
    active = config.active_provider(SMS) if config else MANAGED_SMS
    return active in ("", MANAGED_SMS)


def managed_sms() -> MessageProvider:
    """The WIFI.OS gateway: our account, our key. The ISP pays in credits, not with a
    credential — which is why nothing here comes from their settings."""
    from django.conf import settings

    return AfricasTalkingSMS(
        username=settings.AT_USERNAME,
        api_key=settings.AT_API_KEY,
        sender_id=settings.AT_SENDER_ID,
    )


def resolve_provider(channel: str, operator=None) -> MessageProvider:
    """The real resolution, with no dev short-circuit — so the rule can be tested for
    what it would do in PRODUCTION, not what dev turns it into."""
    config = _messaging_settings(operator)

    if channel == EMAIL:
        if config and config.uses_own(EMAIL):
            return SmtpEmailProvider(
                host=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_username,
                password=config.smtp_password,
                use_tls=config.smtp_use_tls,
                from_email=config.from_email,
                from_name=config.from_name,
            )
        return DjangoEmailProvider()

    if channel == SMS:
        active = config.active_provider(SMS) if config else MANAGED_SMS
        if active in ("", MANAGED_SMS):
            return managed_sms()
        build = SMS_ADAPTERS.get(active)
        if build is None:
            raise ProviderError(f"Unknown SMS provider {active!r}")
        return build(_credentials(operator, SMS, active))

    if channel == WHATSAPP:
        active = config.active_provider(WHATSAPP) if config else ""
        if not active:
            raise ProviderError(
                "WhatsApp is not connected. Choose a provider in "
                "Settings > Communications to send on this channel."
            )
        build = WHATSAPP_ADAPTERS.get(active)
        if build is None:
            raise ProviderError(f"Unknown WhatsApp provider {active!r}")
        return build(_credentials(operator, WHATSAPP, active))

    raise ProviderError(f"Unknown channel {channel!r}")


def get_provider(channel: str, operator=None) -> MessageProvider:
    # Email is safe to exercise for real in dev (Mailpit catches it); the dummy override
    # only shields the channels that cost money.
    if channel != EMAIL and os.getenv("NOTIFICATIONS_PROVIDER") == "dummy":
        return DummyProvider()
    return resolve_provider(channel, operator)


__all__ = [
    "AfricasTalkingSMS",
    "DjangoEmailProvider",
    "DummyProvider",
    "MessageProvider",
    "ProviderError",
    "SendResult",
    "SmtpEmailProvider",
    "get_provider",
    "is_managed_sms",
    "managed_sms",
    "resolve_provider",
]
