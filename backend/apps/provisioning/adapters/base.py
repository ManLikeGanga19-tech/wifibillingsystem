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
    # Bytes the router has counted for this live session, so we can sync usage back
    # for data-cap warnings and reporting. 0 when the router doesn't report them.
    bytes_in: int = 0
    bytes_out: int = 0


@dataclass
class HostEntry:
    """A device the router currently sees on the hotspot LAN — from /ip/hotspot/host,
    named from the DHCP lease where possible. `authorized` is True once it has logged in
    (so it belongs to someone's paid session already); the tap-to-approve discovery only
    offers the ones that aren't."""

    mac_address: str
    ip_address: str = ""
    hostname: str = ""
    authorized: bool = False


@dataclass
class DeviceInfo:
    """A router's hardware identity (stable) + live health (transient)."""

    # Stable identity — persisted on the Router row
    routeros_version: str = ""
    board_name: str = ""
    serial_number: str = ""
    architecture: str = ""
    identity_name: str = ""
    # Live metrics — returned to the caller, never stored
    uptime: str = ""
    cpu_load: int | None = None
    free_memory: int | None = None
    total_memory: int | None = None
    active_users: int | None = None


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

    @abstractmethod
    def get_device_info(self) -> DeviceInfo: ...

    # -- Multi-device sharing (tap-to-approve) -----------------------------
    # One paid session, several of a customer's devices. Default no-ops so an adapter that
    # can't do it (or a future RADIUS one) degrades gracefully rather than breaking callers.
    def list_hosts(self) -> list["HostEntry"]:
        """Devices currently on the hotspot LAN — for the "add your devices" picker."""
        return []

    def login_device(
        self, *, username: str, password: str, mac: str, ip: str = ""
    ) -> ProvisionResult:
        """Log a MAC into the hotspot AS the given account, so it shares that account's
        one time+data budget (the account carries shared-users=N). This is what puts a
        customer's laptop or TV online without a second payment or a portal login on it."""
        return ProvisionResult(ok=True, message="noop")

    def logout_device(self, mac: str) -> ProvisionResult:
        """Drop a single device's live session, without touching the others sharing the
        account — the customer removed it from their plan."""
        return ProvisionResult(ok=True, message="noop")

    # -- PPPoE (broadband) -------------------------------------------------
    # Default no-op implementations so non-PPPoE adapters need not implement them.
    def ensure_pppoe_profile(self, plan) -> ProvisionResult:
        """Create/update the /ppp/profile for a ServicePlan (rate limits)."""
        return ProvisionResult(ok=True, message="noop")

    def create_pppoe_user(self, client) -> ProvisionResult:
        """Create/update the /ppp/secret for a broadband client."""
        return ProvisionResult(ok=True, message="noop")

    def set_pppoe_enabled(self, client, enabled: bool) -> ProvisionResult:
        """Enable (restore) or disable (suspend) a client's PPPoE access, kicking
        the live session on disable."""
        return ProvisionResult(ok=True, message="noop")

    def remove_pppoe_user(self, client) -> ProvisionResult:
        return ProvisionResult(ok=True, message="noop")

    def get_active_pppoe(self) -> list[ActiveSession]:
        return []

    # -- Captive portal ----------------------------------------------------
    def push_portal(self, portal_url: str) -> ProvisionResult:
        """Point this router's captive portal at `portal_url`.

        Called when an ISP changes their subdomain: the redirect baked into the router's
        hotspot login page still names the OLD address, so until this lands their
        customers are being sent somewhere the ISP no longer answers.
        """
        return ProvisionResult(ok=True, message="noop")
