"""Records sends in memory; used in tests and local dev without provider keys."""

from .base import MessageProvider, SendResult


class DummyProvider(MessageProvider):
    sent: list[tuple[str, str]] = []

    def send(self, to_phone: str, body: str) -> SendResult:
        DummyProvider.sent.append((to_phone, body))
        return SendResult(ok=True, provider_ref=f"dummy-{len(DummyProvider.sent)}")
