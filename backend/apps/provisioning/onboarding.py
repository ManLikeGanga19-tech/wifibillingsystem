"""Self-service router onboarding: generate a one-paste RouterOS script that configures the
full WIFI.OS topology, creates the API user, brings up the management tunnel, and phones
home to register.

Design goals:
- The ISP pastes ONE script into their MikroTik terminal, nothing else.
- The script is genuinely IDEMPOTENT — every object is find-or-create/set, so re-pasting
  after an edit never piles up duplicates (the old additive version did, which is what left
  the pilot with two hotspots and three pools).
- The topology matches docs/ROUTER_VLAN_TOPOLOGY.md, validated on the pilot RB951:
  hotspot on VLAN 20, PPPoE on VLAN 30, a tagged trunk on ether3, per-plane firewall
  isolation, and management locked to the WireGuard overlay.
- No secrets are hard-coded by us: the script mints its own API password and reports it back
  over the phone-home call; the router's WireGuard private key is generated server-side and
  streamed once, never stored in a browser.

ASSUMPTIONS (documented in the script header): a RouterOS v7 board of the hAP/RB951 class
where ether1 is the WAN uplink and wlan1 is the 2.4GHz radio. Best run on a fresh/reset
router; idempotent enough to re-run after edits.
"""

import secrets

from django.conf import settings

from .models import Router
from .wireguard import ensure_wireguard_identity, hub_configured, render_router_wg_setup

# Customer planes (see docs/ROUTER_VLAN_TOPOLOGY.md)
HOTSPOT_VLAN = 20
HOTSPOT_GATEWAY = "10.5.50.1"
HOTSPOT_NETWORK = "10.5.50.0/24"
HOTSPOT_POOL = "10.5.50.10-10.5.50.254"
PPPOE_VLAN = 30
PPPOE_GATEWAY = "10.6.0.1"
PPPOE_POOL_RANGE = "10.6.0.10-10.6.0.254"
BRIDGE = "wifios-bridge"


def _platform_base_url() -> str:
    # Where the router POSTs its phone-home. Public base in prod; the callback
    # base doubles as "a URL the outside world can reach us on".
    return settings.DARAJA_CALLBACK_BASE_URL.rstrip("/")


def _portal_base_url(router: Router) -> str:
    """The captive portal THIS router should redirect to — its own ISP's address, not a
    shared one. That is what makes the portal wear the ISP's domain, and it is why a
    subdomain change has to re-push every router (see provisioning.portal_sync)."""
    from apps.core.domains import portal_url_for

    return portal_url_for(router.operator)


def _host_only(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]


def _mgmt_lockdown() -> list[str]:
    """Restrict management services to the WireGuard overlay — the only path the control
    plane uses in production. Skipped until the hub exists (pre-hub the control plane still
    reaches REST over the WAN/LAN, so locking to the overlay would cut it off)."""
    if not hub_configured():
        return [
            "# --- Management services (WireGuard will lock these to the overlay) ---",
            "/ip service set www disabled=no",
        ]
    cidr = settings.WG_OVERLAY_CIDR
    return [
        "# --- Management services locked to the WireGuard overlay only ---",
        f"/ip service set www disabled=no address={cidr}",
        f"/ip service set winbox address={cidr}",
        f"/ip service set ssh address={cidr}",
    ]


def generate_setup_script(router: Router) -> str:
    """Return the one-paste RouterOS script for this router.

    Side effect: mints the router's WireGuard identity (keypair + overlay IP) if it has none,
    so the tunnel stanza can be embedded. Idempotent — calling twice is a no-op.
    """
    ensure_wireguard_identity(router)

    api_password = secrets.token_hex(12)
    platform = _platform_base_url()
    portal = _portal_base_url(router)
    token = router.enrollment_token
    login_redirect = (
        f"{portal}/?mac=$(mac-esc)&ip=$(ip)"
        f"&login=$(link-login-only-esc)&orig=$(link-orig-esc)&router={router.id}"
    )
    wg_stanza = render_router_wg_setup(router)

    lines = [
        f'# ===== WIFI.OS setup for "{router.name}" — hotspot (VLAN {HOTSPOT_VLAN}) + '
        f"PPPoE (VLAN {PPPOE_VLAN}) =====",
        "# Paste into Winbox > New Terminal. RouterOS v7. Idempotent — safe to re-run.",
        "# Assumes ether1 = WAN uplink, wlan1 = 2.4GHz radio. Best on a fresh/reset router.",
        "",
        f':global wifiosApiPass "{api_password}"',
        f':global wifiosToken "{token}"',
        f':global wifiosPlatform "{platform}"',
        "",
        "# --- 1. Least-privilege API user + REST ---",
        ':if ([/user group find name=wifios-api]="") do={ /user group add name=wifios-api '
        'policy=read,write,api,rest-api,!ftp,!telnet,!ssh,!reboot,!sensitive comment="wifi.os" }',
        ':if ([/user find name=wifios]="") do={ /user add name=wifios group=wifios-api '
        "password=$wifiosApiPass comment=\"wifi.os billing API\" } else={ /user set "
        "[find name=wifios] password=$wifiosApiPass group=wifios-api }",
        "",
        "# --- 2. VLAN-filtered bridge (ether1 = WAN, stays out) ---",
        f':if ([/interface bridge find name={BRIDGE}]="") do={{ /interface bridge add '
        f'name={BRIDGE} comment="wifi.os" }}',
        ':foreach i in={"ether2";"ether3";"ether4";"ether5"} do={ '
        f':if ([/interface bridge port find interface=$i]="") do={{ '
        f"/interface bridge port add bridge={BRIDGE} interface=$i }} }}",
        ':if ([/interface wireless find] != "") do={ /interface wireless set [find] '
        'mode=ap-bridge ssid="WIFIOS" disabled=no ; '
        f':if ([/interface bridge port find interface=wlan1]="") do={{ '
        f"/interface bridge port add bridge={BRIDGE} interface=wlan1 }} }}",
        f"/interface bridge port set [find interface=ether2] pvid={PPPOE_VLAN}",
        f"/interface bridge port set [find interface=ether4] pvid={HOTSPOT_VLAN}",
        f"/interface bridge port set [find interface=ether5] pvid={HOTSPOT_VLAN}",
        ':if ([/interface wireless find] != "") do={ /interface bridge port set '
        f"[find interface=wlan1] pvid={HOTSPOT_VLAN} }}",
        f"/interface bridge vlan remove [find bridge={BRIDGE}]",
        f"/interface bridge vlan add bridge={BRIDGE} vlan-ids={HOTSPOT_VLAN} "
        f"untagged=ether4,ether5,wlan1 tagged={BRIDGE},ether3",
        f"/interface bridge vlan add bridge={BRIDGE} vlan-ids={PPPOE_VLAN} "
        f"untagged=ether2 tagged={BRIDGE},ether3",
        f"/interface bridge set [find name={BRIDGE}] vlan-filtering=yes",
        "",
        "# --- 3. VLAN interfaces + addressing ---",
        f':if ([/interface vlan find name=vlan-hotspot]="") do={{ /interface vlan add '
        f"name=vlan-hotspot interface={BRIDGE} vlan-id={HOTSPOT_VLAN} }}",
        f':if ([/interface vlan find name=vlan-pppoe]="") do={{ /interface vlan add '
        f"name=vlan-pppoe interface={BRIDGE} vlan-id={PPPOE_VLAN} }}",
        f':if ([/ip address find interface=vlan-hotspot]="") do={{ /ip address add '
        f'address={HOTSPOT_GATEWAY}/24 interface=vlan-hotspot comment="wifi.os hotspot" }}',
        f':if ([/ip address find interface=vlan-pppoe]="") do={{ /ip address add '
        f'address={PPPOE_GATEWAY}/24 interface=vlan-pppoe comment="wifi.os pppoe" }}',
        "",
        "# --- 4. Pools, hotspot DHCP, DNS ---",
        f':if ([/ip pool find name=hs-pool]="") do={{ /ip pool add name=hs-pool '
        f"ranges={HOTSPOT_POOL} }}",
        f':if ([/ip pool find name=pppoe-pool]="") do={{ /ip pool add name=pppoe-pool '
        f"ranges={PPPOE_POOL_RANGE} }}",
        ':if ([/ip dhcp-server find name=hs-dhcp]="") do={ /ip dhcp-server add name=hs-dhcp '
        "interface=vlan-hotspot address-pool=hs-pool disabled=no } else={ "
        "/ip dhcp-server set [find name=hs-dhcp] interface=vlan-hotspot address-pool=hs-pool }",
        f':if ([/ip dhcp-server network find address={HOTSPOT_NETWORK}]="") do={{ '
        f"/ip dhcp-server network add address={HOTSPOT_NETWORK} gateway={HOTSPOT_GATEWAY} "
        "dns-server=8.8.8.8,1.1.1.1 }",
        "/ip dns set allow-remote-requests=yes",
        "",
        "# --- 5. NAT: both customer nets reach the internet via ether1 ---",
        ':if ([/ip firewall nat find comment="wifi.os internet"]="") do={ /ip firewall nat '
        'add chain=srcnat out-interface=ether1 action=masquerade comment="wifi.os internet" }',
        "",
        "# --- 6. Hotspot on VLAN 20 ---",
        ':if ([/ip hotspot profile find name=wifios-hs]="") do={ /ip hotspot profile add '
        f'name=wifios-hs hotspot-address={HOTSPOT_GATEWAY} login-by=http-chap,http-pap }}',
        ':if ([/ip hotspot find name=wifios-hotspot]="") do={ /ip hotspot add '
        "name=wifios-hotspot interface=vlan-hotspot address-pool=hs-pool profile=wifios-hs "
        "disabled=no } else={ /ip hotspot set [find name=wifios-hotspot] interface=vlan-hotspot }",
        "/ip hotspot user profile set [find name=default] rate-limit=2M/5M",
        f':if ([/ip hotspot walled-garden find comment="wifi.os portal"]="") do={{ '
        f'/ip hotspot walled-garden add dst-host="{_host_only(portal)}" action=allow '
        f'comment="wifi.os portal" }}',
        f':if ([/ip hotspot walled-garden find comment="wifi.os api"]="") do={{ '
        f'/ip hotspot walled-garden add dst-host="{_host_only(platform)}" action=allow '
        f'comment="wifi.os api" }}',
        "",
        "# --- 7. PPPoE on VLAN 30 (profiles carry the pool so clients get an IP) ---",
        ':if ([/ppp profile find name=pppoe-default]="") do={ /ppp profile add '
        f"name=pppoe-default local-address={PPPOE_GATEWAY} remote-address=pppoe-pool "
        "rate-limit=2M/5M }",
        ':if ([/ppp profile find name=wifios-suspended]="") do={ /ppp profile add '
        f"name=wifios-suspended local-address={PPPOE_GATEWAY} remote-address=pppoe-pool "
        "rate-limit=128k/128k }",
        ':if ([/interface pppoe-server server find service-name=wifios]="") do={ '
        "/interface pppoe-server server add service-name=wifios interface=vlan-pppoe "
        "default-profile=pppoe-default disabled=no } else={ /interface pppoe-server server "
        "set [find service-name=wifios] interface=vlan-pppoe default-profile=pppoe-default }",
        "",
        "# --- 8. Firewall: isolate each plane; customers can reach neither mgmt nor each other ---",
        ':if ([/ip firewall filter find comment="wifi.os iso hs-mgmt"]="") do={ '
        "/ip firewall filter add chain=forward action=drop "
        f'src-address={HOTSPOT_NETWORK} dst-address=192.168.0.0/16 comment="wifi.os iso hs-mgmt" }}',
        ':if ([/ip firewall filter find comment="wifi.os iso hs-ppp"]="") do={ '
        "/ip firewall filter add chain=forward action=drop "
        f'src-address={HOTSPOT_NETWORK} dst-address=10.6.0.0/24 comment="wifi.os iso hs-ppp" }}',
        ':if ([/ip firewall filter find comment="wifi.os iso ppp-hs"]="") do={ '
        "/ip firewall filter add chain=forward action=drop "
        f'src-address=10.6.0.0/24 dst-address={HOTSPOT_NETWORK} comment="wifi.os iso ppp-hs" }}',
        *_mgmt_lockdown(),
    ]

    if wg_stanza:
        lines += ["", wg_stanza]

    lines += [
        "",
        "# --- Captive-portal login page ---",
        '/file remove [find name="hotspot/login.html"]',
        "/file add name=\"hotspot/login.html\" contents=\\",
        f'  "<html><head><meta http-equiv=\\"refresh\\" content=\\"0; url={login_redirect}\\">'
        '</head><body>Loading payment page...</body></html>"',
        "",
        "# --- Phone home: register with the platform (idempotent) ---",
        "/tool fetch mode=https http-method=post \\",
        '  url="$wifiosPlatform/api/v1/routers/enroll/" \\',
        '  http-header-field="Content-Type: application/json" \\',
        '  http-data="{\\"token\\":\\"$wifiosToken\\",\\"api_password\\":\\"$wifiosApiPass\\",'
        '\\"version\\":\\"[/system resource get version]\\"}" \\',
        "  output=none",
        f':log info "WIFI.OS setup complete for {router.name}"',
        "# ===== end =====",
    ]
    return "\n".join(lines)
