import os

from .africastalking import AfricasTalkingSMS
from .base import MessageProvider, ProviderError, SendResult
from .dummy import DummyProvider
from .whatsapp import WhatsAppCloud


def get_provider(channel: str) -> MessageProvider:
    if os.getenv("NOTIFICATIONS_PROVIDER") == "dummy":
        return DummyProvider()
    if channel == "sms":
        return AfricasTalkingSMS()
    if channel == "whatsapp":
        return WhatsAppCloud()
    raise ProviderError(f"Unknown channel {channel!r}")


__all__ = [
    "AfricasTalkingSMS",
    "DummyProvider",
    "MessageProvider",
    "ProviderError",
    "SendResult",
    "WhatsAppCloud",
    "get_provider",
]
