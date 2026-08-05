"""The onboarding script generator must emit the validated VLAN topology, idempotently.

Content-level assertions: we can't run RouterOS here, but we can pin that the script builds
the right planes, carries PPPoE addressing (the bug that bit us), isolates customers, and is
find-or-create everywhere rather than the old additive form that piled up duplicates.
"""

import pytest
from django.test import override_settings

from apps.provisioning.onboarding import generate_setup_script
from tests.factories import RouterFactory

pytestmark = pytest.mark.django_db

HUB = dict(WG_HUB_ENDPOINT="hub.wifios.co.ke:51820", WG_HUB_PUBLIC_KEY="HUBPUBKEY000=")


def _script(**settings):
    with override_settings(**settings):
        return generate_setup_script(RouterFactory())


def test_builds_both_vlans():
    s = _script()
    assert "vlan-id=20" in s and "vlan-id=30" in s
    assert "vlan-filtering=yes" in s
    assert "interface=vlan-hotspot" in s and "interface=vlan-pppoe" in s
    assert "vlan-ids=30 untagged=ether2" in s  # PPPoE access port
    assert "tagged=wifios-bridge,ether3" in s  # trunk


def test_pppoe_profiles_carry_addressing():
    """The bug we fixed on hardware: PPPoE profiles must include the pool + gateway."""
    s = _script()
    assert "local-address=10.6.0.1 remote-address=pppoe-pool" in s
    assert "name=wifios-suspended" in s  # suspend-redirect profile


def test_customer_isolation_rules_present():
    s = _script()
    assert "wifi.os iso hs-mgmt" in s
    assert "wifi.os iso hs-ppp" in s
    assert "wifi.os iso ppp-hs" in s


def test_is_idempotent_not_additive():
    """Every object is find-or-create/set — the old version used bare `add` and duplicated."""
    s = _script()
    assert ':if ([/user group find name=wifios-api]="")' in s
    assert "else={ /user set [find name=wifios]" in s
    assert ':if ([/ip pool find name=pppoe-pool]="")' in s
    assert ':if ([/interface bridge find name=wifios-bridge]="")' in s


def test_no_wireguard_or_lockdown_before_hub():
    s = _script()
    assert "wg-wifios" not in s
    assert "address=10.88.0.0/16" not in s  # www stays open until the overlay exists
    assert "/ip service set www disabled=no" in s


@override_settings(**HUB)
def test_wireguard_and_lockdown_once_hub_exists():
    s = generate_setup_script(RouterFactory())
    assert "/interface wireguard add name=wg-wifios" in s
    assert "endpoint-address=hub.wifios.co.ke" in s
    # management services locked to the overlay
    assert "/ip service set www disabled=no address=10.88.0.0/16" in s
    assert "/ip service set winbox address=10.88.0.0/16" in s
