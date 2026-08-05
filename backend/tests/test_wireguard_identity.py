"""WireGuard identity: keypair generation + overlay-IP allocation.

The foundation of the management plane. These pin the two security-critical invariants:
keys are valid Curve25519 material, and no two routers ever get the same /32.
"""

import base64

import pytest
from django.test import override_settings

from apps.provisioning.wireguard import (
    OverlayExhausted,
    ensure_wireguard_identity,
    generate_keypair,
)
from tests.factories import RouterFactory

pytestmark = pytest.mark.django_db


def test_keypair_is_valid_curve25519():
    priv, pub = generate_keypair()
    # 32 raw bytes, base64-encoded (44 chars incl. padding) — WireGuard's wire format.
    assert len(base64.b64decode(priv)) == 32
    assert len(base64.b64decode(pub)) == 32
    assert priv != pub


def test_keypairs_are_unique():
    assert len({generate_keypair()[0] for _ in range(20)}) == 20


def test_ensure_identity_assigns_key_and_overlay_ip():
    r = RouterFactory()
    assert ensure_wireguard_identity(r) is True
    r.refresh_from_db()
    assert r.wg_private_key and r.wg_public_key
    assert r.overlay_ip
    assert base64.b64decode(r.wg_private_key)  # decrypts + is real key material


def test_ensure_identity_is_idempotent():
    r = RouterFactory()
    ensure_wireguard_identity(r)
    first_ip, first_key = r.overlay_ip, r.wg_private_key
    assert ensure_wireguard_identity(r) is False  # no-op second time
    r.refresh_from_db()
    assert r.overlay_ip == first_ip
    assert r.wg_private_key == first_key


@override_settings(WG_OVERLAY_CIDR="10.88.0.0/29", WG_HUB_IP="10.88.0.1")
def test_allocation_is_unique_and_skips_hub():
    ips = []
    for _ in range(4):
        r = RouterFactory()
        ensure_wireguard_identity(r)
        r.refresh_from_db()
        ips.append(r.overlay_ip)
    assert len(set(ips)) == len(ips)          # never double-assigned
    assert "10.88.0.1" not in ips             # hub is skipped
    assert all(ip.startswith("10.88.0.") for ip in ips)


@override_settings(WG_OVERLAY_CIDR="10.88.0.0/30", WG_HUB_IP="10.88.0.1")
def test_overlay_exhaustion_raises():
    # /30 → hosts .1 and .2; .1 is the hub, so exactly ONE assignable /32.
    ensure_wireguard_identity(RouterFactory())
    with pytest.raises(OverlayExhausted):
        ensure_wireguard_identity(RouterFactory())
