"""WireGuard-aware enrollment: the router's tunnel stanza + overlay-IP addressing.

Once the hub exists, the control plane must address a router at its stable overlay /32 —
never its CGNAT source IP. Before the hub exists, onboarding still works the old way.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.provisioning.models import Router
from apps.provisioning.wireguard import (
    ensure_wireguard_identity,
    hub_configured,
    render_router_wg_setup,
)
from tests.factories import RouterFactory

pytestmark = pytest.mark.django_db

HUB = dict(WG_HUB_ENDPOINT="hub.wifios.co.ke:51820", WG_HUB_PUBLIC_KEY="HUBPUBKEY000=")


def test_no_stanza_until_hub_is_configured():
    r = RouterFactory()
    ensure_wireguard_identity(r)
    assert hub_configured() is False
    assert render_router_wg_setup(r) == ""  # falls back to LAN model


@override_settings(**HUB)
def test_stanza_carries_identity_and_hub_peer():
    r = RouterFactory()
    ensure_wireguard_identity(r)
    r.refresh_from_db()
    script = render_router_wg_setup(r)
    assert r.wg_private_key in script          # router's own key, embedded by design
    assert f"address={r.overlay_ip}/32" in script
    assert 'public-key="HUBPUBKEY000="' in script
    assert "endpoint-address=hub.wifios.co.ke" in script
    assert "endpoint-port=51820" in script
    assert "allowed-address=10.88.0.0/16" in script
    assert "persistent-keepalive=25s" in script


@override_settings(**HUB)
def test_enroll_uses_overlay_ip_when_hub_live():
    r = RouterFactory(provisioning_backend=Router.Backend.MIKROTIK_REST)
    ensure_wireguard_identity(r)
    r.refresh_from_db()
    resp = pytest.importorskip("rest_framework.test").APIClient().post(
        reverse("router-enroll"),
        {"token": r.enrollment_token, "api_password": "secret", "version": "7.16"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    r.refresh_from_db()
    assert r.management_host == r.overlay_ip
    assert r.wg_enrolled_at is not None


def test_enroll_falls_back_to_source_ip_without_hub():
    r = RouterFactory(provisioning_backend=Router.Backend.MIKROTIK_REST)
    ensure_wireguard_identity(r)
    from rest_framework.test import APIClient

    resp = APIClient().post(
        reverse("router-enroll"),
        {"token": r.enrollment_token, "api_password": "secret", "version": "7.16"},
        format="json",
        REMOTE_ADDR="203.0.113.9",
    )
    assert resp.status_code == 200, resp.content
    r.refresh_from_db()
    assert r.management_host == "203.0.113.9"  # the phone-home source
