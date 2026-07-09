"""Records sends in memory; used in tests and local dev without provider keys."""

from .base import MessageProvider, SendResult


class DummyProvider(MessageProvider):
    sent: list[tuple[str, str]] = []  # (recipient, body) — reset in tests

    def send(self, message) -> SendResult:
        DummyProvider.sent.append((message.recipient, message.body))
        return SendResult(ok=True, provider_ref=f"dummy-{len(DummyProvider.sent)}")
