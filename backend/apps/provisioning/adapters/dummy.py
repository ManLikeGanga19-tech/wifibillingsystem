"""No-op adapter for development and tests. Records calls so tests can assert on them."""

from .base import ActiveSession, DeviceInfo, HostEntry, ProvisioningAdapter, ProvisionResult


class DummyAdapter(ProvisioningAdapter):
    calls: list[tuple] = []  # class-level, shared across instances (reset in tests)
    #: Tests set this to drive usage sync: {username: (bytes_in, bytes_out)}.
    usage: dict[str, tuple[int, int]] = {}
    #: Tests set this to drive device discovery: {mac: (ip, hostname, authorized)}.
    hosts: dict[str, tuple[str, str, bool]] = {}
    #: MACs logged in via login_device — so tests (and discovery) know they're now on.
    logged_in: set[str] = set()

    def activate_user(self, session) -> ProvisionResult:
        DummyAdapter.calls.append(("activate", session.hotspot_username))
        return ProvisionResult(ok=True, message="dummy activated")

    def suspend_user(self, session) -> ProvisionResult:
        DummyAdapter.calls.append(("suspend", session.hotspot_username))
        return ProvisionResult(ok=True, message="dummy suspended")

    def get_active_sessions(self) -> list[ActiveSession]:
        return [
            ActiveSession(username=user, bytes_in=bi, bytes_out=bo)
            for user, (bi, bo) in DummyAdapter.usage.items()
        ]

    def test_connection(self) -> bool:
        return True

    def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            routeros_version="7.x (dummy)",
            board_name="DummyBoard",
            serial_number="DUMMY-0000",
            architecture="test",
            uptime="0s",
            cpu_load=0,
            active_users=0,
        )

    # -- PPPoE (records calls for test assertions) ------------------------
    def ensure_pppoe_profile(self, plan) -> ProvisionResult:
        DummyAdapter.calls.append(("ensure_profile", plan.mikrotik_profile))
        return ProvisionResult(ok=True)

    def create_pppoe_user(self, client) -> ProvisionResult:
        DummyAdapter.calls.append(("pppoe_create", client.pppoe_username))
        return ProvisionResult(ok=True)

    def set_pppoe_enabled(self, client, enabled: bool) -> ProvisionResult:
        action = "pppoe_enable" if enabled else "pppoe_suspend"
        DummyAdapter.calls.append((action, client.pppoe_username))
        return ProvisionResult(ok=True)

    def remove_pppoe_user(self, client) -> ProvisionResult:
        DummyAdapter.calls.append(("pppoe_remove", client.pppoe_username))
        return ProvisionResult(ok=True)

    #: Tests set this to drive PPPoE metering:
    #: {pppoe_username: (download_bytes, upload_bytes, ip, uptime, mac)}.
    pppoe_active: dict = {}

    def get_active_pppoe(self) -> list[ActiveSession]:
        out = []
        for user, v in DummyAdapter.pppoe_active.items():
            down, up = v[0], v[1]
            out.append(
                ActiveSession(
                    username=user,
                    bytes_in=down,
                    bytes_out=up,
                    ip_address=v[2] if len(v) > 2 else "10.10.0.2",
                    uptime=v[3] if len(v) > 3 else "1h",
                    mac_address=v[4] if len(v) > 4 else "",
                )
            )
        return out

    # -- Multi-device sharing ---------------------------------------------
    #: Tests set this to make the router refuse a device login, exercising the rollback.
    login_fails: bool = False

    def list_hosts(self) -> list[HostEntry]:
        out = []
        for mac, v in DummyAdapter.hosts.items():
            ip, hostname = (v[0], v[1]) if len(v) > 1 else ("", "")
            seeded_auth = v[2] if len(v) > 2 else False
            out.append(
                HostEntry(
                    mac_address=mac,
                    ip_address=ip,
                    hostname=hostname,
                    authorized=seeded_auth or mac in DummyAdapter.logged_in,
                )
            )
        return out

    def login_device(self, *, username, password, mac, ip="") -> ProvisionResult:
        DummyAdapter.calls.append(("login_device", mac, username))
        if DummyAdapter.login_fails:
            from .base import ProvisioningError

            raise ProvisioningError("dummy router refused the device login")
        DummyAdapter.logged_in.add(mac)
        return ProvisionResult(ok=True, message=f"dummy login {mac} as {username}")

    def logout_device(self, mac) -> ProvisionResult:
        DummyAdapter.calls.append(("logout_device", mac))
        DummyAdapter.logged_in.discard(mac)
        return ProvisionResult(ok=True, message=f"dummy logout {mac}")

    # -- Captive portal ---------------------------------------------------
    #: Tests set this to make a router refuse the new address, so the "one router did not
    #: get the memo" path is exercised rather than assumed.
    portal_fails: bool = False

    def push_portal(self, portal_url: str) -> ProvisionResult:
        DummyAdapter.calls.append(("push_portal", portal_url))
        if DummyAdapter.portal_fails:
            from .base import ProvisioningError

            raise ProvisioningError("dummy router refused the portal push")
        return ProvisionResult(ok=True, message=f"dummy portal -> {portal_url}")
