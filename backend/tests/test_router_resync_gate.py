"""Re-sync gating on reachability (not self-onboarding) + factory-reset detection.

The two fixes:
  1. A hand-configured router (is_enrolled False) can still be re-synced.
  2. 'needs onboarding' means the API user is GONE (auth failure), not merely
     powered off — a temporarily offline router recovers on its own.
"""

import httpx
import pytest

from apps.provisioning.adapters import ProvisioningAuthError
from apps.provisioning.adapters.mikrotik import MikroTikRestAdapter
from apps.provisioning.models import Router

from .factories import OperatorFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db


def staff_client(operator):
    from rest_framework.test import APIClient

    from apps.accounts.models import Role

    c = APIClient()
    c.force_authenticate(user=UserFactory(operator=operator, is_staff=True, role=Role.TENANT_OWNER))
    return c


class TestReachabilityModel:
    def test_hand_configured_router_is_reachable_though_not_enrolled(self):
        r = RouterFactory(
            provisioning_backend=Router.Backend.MIKROTIK_REST,
            management_host="10.0.0.5",
            password="secret",
        )
        assert r.is_enrolled is False  # never ran the self-onboarding script
        assert r.is_reachable is True  # ...but we have working credentials
        assert r.needs_onboarding is False

    def test_router_without_credentials_needs_onboarding(self):
        r = RouterFactory(
            provisioning_backend=Router.Backend.MIKROTIK_REST,
            management_host="",
            password="",
        )
        assert r.needs_onboarding is True

    def test_auth_failure_flag_marks_needs_onboarding(self):
        r = RouterFactory(
            provisioning_backend=Router.Backend.MIKROTIK_REST,
            management_host="10.0.0.5",
            password="secret",
        )
        assert r.needs_onboarding is False
        r.onboarding_required = True  # a factory reset was detected
        assert r.is_reachable is False
        assert r.needs_onboarding is True


class TestResyncEndpoint:
    def test_resync_allowed_for_hand_configured_router(self, mocker):
        op = OperatorFactory()
        r = RouterFactory(operator=op, provisioning_backend=Router.Backend.DUMMY)
        assert r.is_enrolled is False
        mocker.patch("apps.provisioning.views.sync_router.delay")
        resp = staff_client(op).post(f"/api/v1/routers/{r.id}/resync/")
        assert resp.status_code == 202  # previously 409 "not enrolled"

    def test_resync_blocked_when_needs_onboarding(self):
        op = OperatorFactory()
        r = RouterFactory(
            operator=op,
            provisioning_backend=Router.Backend.MIKROTIK_REST,
            management_host="",
            password="",
        )
        resp = staff_client(op).post(f"/api/v1/routers/{r.id}/resync/")
        assert resp.status_code == 409
        assert resp.json()["needs_onboarding"] is True


class TestDeviceIdentity:
    def test_refresh_persists_stable_identity(self, mocker):
        from apps.provisioning.adapters.base import DeviceInfo
        from apps.provisioning.services import refresh_device_identity

        r = RouterFactory(provisioning_backend=Router.Backend.MIKROTIK_REST,
                          management_host="10.0.0.5", password="secret")
        mocker.patch(
            "apps.provisioning.adapters.mikrotik.MikroTikRestAdapter.get_device_info",
            return_value=DeviceInfo(
                routeros_version="7.16.2", board_name="RB951Ui-2HnD",
                serial_number="HJY0AH8N5GE", architecture="mipsbe",
                uptime="2h40m", cpu_load=1, active_users=3,
            ),
        )
        info = refresh_device_identity(r)
        r.refresh_from_db()
        assert r.routeros_version == "7.16.2"
        assert r.board_name == "RB951Ui-2HnD"
        assert r.serial_number == "HJY0AH8N5GE"
        assert r.architecture == "mipsbe"
        assert r.identity_updated_at is not None
        # live metrics returned but NOT stored on the row
        assert info.active_users == 3
        assert not hasattr(r, "active_users")

    def test_device_info_endpoint(self, mocker):
        from apps.provisioning.adapters.base import DeviceInfo

        op = OperatorFactory()
        r = RouterFactory(operator=op, provisioning_backend=Router.Backend.MIKROTIK_REST,
                          management_host="10.0.0.5", password="secret")
        mocker.patch(
            "apps.provisioning.adapters.mikrotik.MikroTikRestAdapter.get_device_info",
            return_value=DeviceInfo(routeros_version="7.16.2", board_name="RB951Ui-2HnD",
                                    uptime="2h40m", cpu_load=5, active_users=2),
        )
        resp = staff_client(op).get(f"/api/v1/routers/{r.id}/device_info/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["board_name"] == "RB951Ui-2HnD"
        assert body["active_users"] == 2
        assert body["uptime"] == "2h40m"


class TestAuthFailureDetection:
    def _adapter(self):
        r = RouterFactory(
            provisioning_backend=Router.Backend.MIKROTIK_REST,
            management_host="10.0.0.5",
            password="secret",
        )
        return MikroTikRestAdapter(r)

    def test_401_raises_auth_error(self, mocker):
        adapter = self._adapter()
        mock_client = mocker.MagicMock()
        mock_resp = mocker.MagicMock(status_code=401)
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = mocker.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch.object(adapter, "_client", return_value=mock_client)
        with pytest.raises(ProvisioningAuthError):
            adapter.test_connection()

    def test_timeout_is_offline_not_auth_failure(self, mocker):
        adapter = self._adapter()
        mock_client = mocker.MagicMock()
        mock_client.get.side_effect = httpx.ConnectTimeout("timed out")
        mock_client.__enter__ = mocker.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch.object(adapter, "_client", return_value=mock_client)
        # A powered-off router: offline, but NOT an auth failure — config intact.
        assert adapter.test_connection() is False
