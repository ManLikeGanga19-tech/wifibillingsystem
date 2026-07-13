"""Choosing WHOSE gateway a message leaves on.

The hybrid rule, in one place:

  1. Dev/test override (NOTIFICATIONS_PROVIDER=dummy) — nothing paid ever leaves the box.
  2. The ISP's OWN credentials, if they configured this channel and the credentials are
     actually there (MessagingSettings.uses_own guards the half-configured case).
  3. The PLATFORM's credentials — the default, so messaging works on day one with
     nothing to set up.

WhatsApp is the exception: there is no platform account, so an ISP who hasn't brought
their own gets an explicit "switched off" error rather than a silent black hole.
"""

import os

from .africastalking import AfricasTalkingSMS
from .base import MessageProvider, ProviderError, SendResult
from .dummy import DummyProvider
from .email import DjangoEmailProvider, SmtpEmailProvider
from .whatsapp import WhatsAppCloud

SMS = "sms"
EMAIL = "email"
WHATSAPP = "whatsapp"


def _messaging_settings(operator):
    if operator is None:
        return None
    from ..models import MessagingSettings

    return MessagingSettings.objects.filter(operator=operator).first()


def resolve_provider(channel: str, operator=None) -> MessageProvider:
    """The real resolution: own credentials, else the platform's. No dummy override —
    kept separate from get_provider so the hybrid rule can be tested for what it would
    do in production, not what dev short-circuits it to."""
    from django.conf import settings

    config = _messaging_settings(operator)
    own = bool(config and config.uses_own(channel))

    if channel == SMS:
        if own:
            return AfricasTalkingSMS(
                username=config.sms_username,
                api_key=config.sms_api_key,
                sender_id=config.sms_sender_id,
            )
        return AfricasTalkingSMS(
            username=settings.AT_USERNAME,
            api_key=settings.AT_API_KEY,
            sender_id=settings.AT_SENDER_ID,
        )

    if channel == EMAIL:
        if own:
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

    if channel == WHATSAPP:
        if own:
            return WhatsAppCloud(
                phone_number_id=config.whatsapp_phone_number_id,
                token=config.whatsapp_token,
            )
        if config is not None:
            # They have settings and haven't brought a WhatsApp account: say so.
            raise ProviderError(
                "WhatsApp is switched off. Add your WhatsApp Business credentials in "
                "Settings > Communications to send on this channel."
            )
        return WhatsAppCloud(
            phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID,
            token=settings.WHATSAPP_TOKEN,
        )

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
    "WhatsAppCloud",
    "get_provider",
    "resolve_provider",
]
