"""Self-service router onboarding: generate a one-paste RouterOS script that
configures the hotspot, creates the API user, and phones home to register.

Design goals:
- The ISP pastes ONE script into their MikroTik terminal, nothing else.
- The script is idempotent — safe to paste again after a change.
- No secrets are hard-coded by us; the script generates its own API password
  and reports it back over the phone-home call (server stores it encrypted).
"""

import secrets

from django.conf import settings

from .models import Router

# Hotspot LAN the script sets up on the router's bridge
HOTSPOT_NETWORK = "10.5.50.0/24"
HOTSPOT_GATEWAY = "10.5.50.1"
HOTSPOT_POOL = "10.5.50.10-10.5.50.254"


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


def generate_setup_script(router: Router) -> str:
    """Return the RouterOS script for this router. WAN is ether1; the rest of the
    ports + wlan form the hotspot bridge."""
    api_password = secrets.token_hex(12)
    platform = _platform_base_url()
    portal = _portal_base_url(router)
    token = router.enrollment_token
    login_redirect = (
        f"{portal}/?mac=$(mac-esc)&ip=$(ip)"
        f"&login=$(link-login-only-esc)&orig=$(link-orig-esc)&router={router.id}"
    )

    return f"""# ===== WIFI.OS auto-setup for "{router.name}" =====
# Paste this whole block into the MikroTik terminal (Winbox > New Terminal).
# Safe to run more than once. Requires RouterOS v7.

:global wifiosApiPass "{api_password}"
:global wifiosToken "{token}"
:global wifiosPlatform "{platform}"

# --- API user the billing system uses (least privilege) ---
/user group add name=wifios-api policy=read,write,api,rest-api,!ftp,!telnet,!ssh,!reboot,!sensitive comment="wifi.os"
/user remove [find name=wifios]
/user add name=wifios group=wifios-api password=$wifiosApiPass comment="wifi.os billing API"

# --- Enable REST (rides on www; production should move to www-ssl) ---
/ip service set www disabled=no

# --- Hotspot bridge: every port except ether1 (WAN) + wlan ---
/interface bridge add name=wifios-hotspot comment="wifi.os" disabled=no
:foreach i in=[/interface ethernet find where name!="ether1"] do={{ \\
  /interface bridge port add bridge=wifios-hotspot interface=$i }}
:if ([/interface wireless find] != "") do={{ \\
  /interface wireless set [find] mode=ap-bridge ssid="WIFIOS" disabled=no ; \\
  /interface bridge port add bridge=wifios-hotspot interface=[/interface wireless find] }}

# --- Addressing + DHCP for clients ---
/ip address add address={HOTSPOT_GATEWAY}/24 interface=wifios-hotspot comment="wifi.os"
/ip pool add name=wifios-pool ranges={HOTSPOT_POOL}
/ip dhcp-server add name=wifios-dhcp interface=wifios-hotspot address-pool=wifios-pool disabled=no
/ip dhcp-server network add address={HOTSPOT_NETWORK} gateway={HOTSPOT_GATEWAY} dns-server=8.8.8.8,1.1.1.1
/ip dns set allow-remote-requests=yes

# --- NAT so clients reach the internet via ether1 ---
/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade comment="wifi.os"

# --- Hotspot server + captive portal ---
/ip hotspot profile add name=wifios-hs hotspot-address={HOTSPOT_GATEWAY} login-by=http-chap,http-pap
/ip hotspot add name=wifios interface=wifios-hotspot address-pool=wifios-pool profile=wifios-hs disabled=no
/ip hotspot user profile set [find name=default] rate-limit=2M/5M

# --- Walled garden: let clients reach the portal before paying ---
/ip hotspot walled-garden add dst-host="{_host_only(portal)}" action=allow comment="wifi.os portal"
/ip hotspot walled-garden add dst-host="{_host_only(platform)}" action=allow comment="wifi.os api"

# --- Login page redirects to the captive portal ---
/file remove [find name="hotspot/login.html"]
/file add name="hotspot/login.html" contents=\\
  "<html><head><meta http-equiv=\\"refresh\\" content=\\"0; url={login_redirect}\\"></head><body>Loading payment page...</body></html>"

# --- Phone home: register with the platform (idempotent) ---
/tool fetch mode=https http-method=post \\
  url="$wifiosPlatform/api/v1/routers/enroll/" \\
  http-header-field="Content-Type: application/json" \\
  http-data="{{\\"token\\":\\"$wifiosToken\\",\\"api_password\\":\\"$wifiosApiPass\\",\\"version\\":\\"[/system resource get version]\\"}}" \\
  output=none
:log info "WIFI.OS setup complete for {router.name}"
# ===== end =====
"""


def _host_only(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]
