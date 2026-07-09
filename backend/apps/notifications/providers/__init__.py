import os

from .africastalking import AfricasTalkingSMS
from .base import MessageProvider, ProviderError, SendResult
from .dummy import DummyProvider
from .email import DjangoEmailProvider
from .whatsapp import WhatsAppCloud


def get_provider(channel: str) -> MessageProvider:
    # Email always goes through Django mail (console backend in dev is already safe);
    # the dummy override only applies to paid SMS/WhatsApp providers.
    if channel == "email":
        return DjangoEmailProvider()
    if os.getenv("NOTIFICATIONS_PROVIDER") == "dummy":
        return DummyProvider()
    if channel == "sms":
        return AfricasTalkingSMS()
    if channel == "whatsapp":
        return WhatsAppCloud()
    raise ProviderError(f"Unknown channel {channel!r}")


__all__ = [
    "AfricasTalkingSMS",
    "DjangoEmailProvider",
    "DummyProvider",
    "MessageProvider",
    "ProviderError",
    "SendResult",
    "WhatsAppCloud",
    "get_provider",
]
