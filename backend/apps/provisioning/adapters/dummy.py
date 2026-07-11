"""No-op adapter for development and tests. Records calls so tests can assert on them."""

from .base import ActiveSession, DeviceInfo, ProvisioningAdapter, ProvisionResult


class DummyAdapter(ProvisioningAdapter):
    calls: list[tuple] = []  # class-level, shared across instances (reset in tests)

    def activate_user(self, session) -> ProvisionResult:
        DummyAdapter.calls.append(("activate", session.hotspot_username))
        return ProvisionResult(ok=True, message="dummy activated")

    def suspend_user(self, session) -> ProvisionResult:
        DummyAdapter.calls.append(("suspend", session.hotspot_username))
        return ProvisionResult(ok=True, message="dummy suspended")

    def get_active_sessions(self) -> list[ActiveSession]:
        return []

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
