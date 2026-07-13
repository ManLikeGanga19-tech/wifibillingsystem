"""No-op adapter for development and tests. Records calls so tests can assert on them."""

from .base import ActiveSession, DeviceInfo, ProvisioningAdapter, ProvisionResult


class DummyAdapter(ProvisioningAdapter):
    calls: list[tuple] = []  # class-level, shared across instances (reset in tests)
    #: Tests set this to drive usage sync: {username: (bytes_in, bytes_out)}.
    usage: dict[str, tuple[int, int]] = {}

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

    def get_active_pppoe(self) -> list[ActiveSession]:
        return []

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
