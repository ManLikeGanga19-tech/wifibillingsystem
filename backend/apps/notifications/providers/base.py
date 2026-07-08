from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(Exception):
    pass


@dataclass
class SendResult:
    ok: bool
    provider_ref: str = ""
    error: str = ""


class MessageProvider(ABC):
    @abstractmethod
    def send(self, to_phone: str, body: str) -> SendResult: ...
