"""WireGuard hub reconciler + tunnel health — the SERVER side of the management plane.

These pin the two guarantees that matter for staging safety:
  * the reconciler only RENDERS text from the DB — it never reaches a router or the hub, so
    it can't disturb a live customer; and
  * tunnel health is a pure read of the last handshake we already observed.
"""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.provisioning.wireguard import (
    ensure_wireguard_identity,
    render_hub_config,
    render_hub_peers,
    tunnel_health,
)
from tests.factories import OperatorFactory, RouterFactory, UserFactory

pytestmark = pytest.mark.django_db

HUB = dict(
    WG_HUB_ENDPOINT="hub.wifios.co.ke:51820",
    WG_HUB_PUBLIC_KEY="aGVsbG8=",
    WG_OVERLAY_CIDR="10.88.0.0/16",
    WG_HUB_IP="10.88.0.1",
)


def _enrolled(slug="op", name="R1"):
    op = OperatorFactory(slug=slug)
    r = RouterFactory(operator=op, name=name)
    ensure_wireguard_identity(r)
    return r


class TestHubReconciler:
    def test_peers_list_one_block_per_enrolled_router(self):
        a = _enrolled("op-a", "Alpha")
        b = _enrolled("op-b", "Bravo")
        peers = render_hub_peers()
        assert peers.count("[Peer]") == 2
        assert a.wg_public_key in peers and b.wg_public_key in peers
        assert f"{a.overlay_ip}/32" in peers  # locked to its own /32

    def test_unenrolled_routers_are_absent(self):
        _enrolled("op-a", "Alpha")
        RouterFactory(operator=OperatorFactory(slug="op-b"), name="NoWG")  # no identity
        assert render_hub_peers().count("[Peer]") == 1

    def test_inactive_router_drops_out_of_the_peer_set(self):
        r = _enrolled("op-a", "Alpha")
        r.is_active = False
        r.save(update_fields=["is_active"])
        assert render_hub_peers() == ""

    @override_settings(**HUB)
    def test_full_config_has_interface_and_placeholder_key_when_unset(self):
        _enrolled("op-a", "Alpha")
        cfg = render_hub_config()
        assert "[Interface]" in cfg and "ListenPort = 51820" in cfg
        assert "10.88.0.1/16" in cfg
        assert "<SET WG_HUB_PRIVATE_KEY ON THE HUB>" in cfg  # secret never invented here

    @override_settings(**HUB, WG_HUB_PRIVATE_KEY="c2VjcmV0")
    def test_full_config_uses_the_hub_key_when_present(self):
        _enrolled("op-a", "Alpha")
        assert "PrivateKey = c2VjcmV0" in render_hub_config()


class TestTunnelHealth:
    def test_states_up_stale_and_down(self):
        now = timezone.now()
        up = _enrolled("op-up", "Up")
        up.wg_last_handshake_at = now
        up.save(update_fields=["wg_last_handshake_at"])
        stale = _enrolled("op-stale", "Stale")
        stale.wg_last_handshake_at = now - timedelta(hours=2)
        stale.save(update_fields=["wg_last_handshake_at"])
        _enrolled("op-down", "Down")  # never handshook

        by_name = {h["name"]: h["state"] for h in tunnel_health()}
        assert by_name == {"Up": "up", "Stale": "stale", "Down": "down"}

    def test_router_without_identity_is_na(self):
        RouterFactory(operator=OperatorFactory(slug="noid"), name="NoId")
        # tunnel_health only lists enrolled peers, so a no-identity router simply isn't there
        assert tunnel_health() == []


class TestEndpoints:
    def _platform(self, owner=True):
        role = Role.PLATFORM_OWNER if owner else Role.PLATFORM_SUPPORT
        c = APIClient()
        c.force_authenticate(user=UserFactory(is_staff=True, role=role))
        return c

    @override_settings(**HUB)
    def test_hub_config_is_owner_only(self):
        _enrolled("op-a", "Alpha")
        assert self._platform(owner=True).get("/api/v1/wireguard/hub-config/").status_code == 200
        assert self._platform(owner=False).get("/api/v1/wireguard/hub-config/").status_code == 403

    def test_health_is_platform_staff(self):
        _enrolled("op-a", "Alpha")
        r = self._platform(owner=False).get("/api/v1/wireguard/health/")
        assert r.status_code == 200
        assert "routers" in r.json()

    def test_health_refused_to_non_platform(self):
        op = OperatorFactory(slug="tenant")
        c = APIClient()
        c.force_authenticate(user=UserFactory(operator=op, role=Role.TENANT_OWNER))
        assert c.get("/api/v1/wireguard/health/").status_code == 403
