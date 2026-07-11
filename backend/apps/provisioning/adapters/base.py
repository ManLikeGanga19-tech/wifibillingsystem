"""Provisioning abstraction. MikroTik REST today; a RADIUS adapter can replace it
later without touching any caller — everything goes through this interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProvisioningError(Exception):
    pass


class ProvisioningAuthError(ProvisioningError):
    """The router answered but rejected our credentials — its API user is gone
    (typically a factory reset). Distinct from being merely unreachable/offline:
    this one means the ISP must re-run the setup script."""


@dataclass
class ProvisionResult:
    ok: bool
    message: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ActiveSession:
    username: str
    mac_address: str = ""
    ip_address: str = ""
    uptime: str = ""


class ProvisioningAdapter(ABC):
    def __init__(self, router):
        self.router = router

    @abstractmethod
    def activate_user(self, session) -> ProvisionResult: ...

    @abstractmethod
    def suspend_user(self, session) -> ProvisionResult: ...

    @abstractmethod
    def get_active_sessions(self) -> list[ActiveSession]: ...

    @abstractmethod
    def test_connection(self) -> bool: ...
