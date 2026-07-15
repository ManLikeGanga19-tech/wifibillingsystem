"""RouterOS v7 REST API adapter.

Uses /ip/hotspot/user for credentials and /ip/hotspot/active for live sessions.
limit-uptime is set on the hotspot user so the router enforces cutoff even if
this server is unreachable at expiry time (belt and braces with expire_sessions).
"""

import logging

import httpx

from .base import (
    ActiveSession,
    DeviceInfo,
    HostEntry,
    ProvisioningAdapter,
    ProvisioningAuthError,
    ProvisioningError,
    ProvisionResult,
)


def _safe_json(resp) -> dict:
    """RouterOS command endpoints sometimes answer 200 with an empty body."""
    try:
        body = resp.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {"result": body}

# PPPoE profile a suspended (overdue) client is moved onto. The router should have
# this profile firewalled to a walled garden that redirects http to a pay page.
SUSPENDED_PROFILE = "wifios-suspended"


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

logger = logging.getLogger(__name__)


def _ros_duration(seconds: int) -> str:
    """3900 -> '1h5m0s' (RouterOS time format)."""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m}m{s}s"


class MikroTikRestAdapter(ProvisioningAdapter):
    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.router.rest_base_url,
            auth=(self.router.username, self.router.password or ""),
            verify=self.router.verify_tls,
            timeout=15,
        )

    def _find_user_id(self, client: httpx.Client, username: str) -> str | None:
        resp = client.get("/ip/hotspot/user", params={"name": username})
        resp.raise_for_status()
        users = resp.json()
        return users[0][".id"] if users else None

    def activate_user(self, session) -> ProvisionResult:
        plan = session.plan
        payload = {
            "name": session.hotspot_username,
            "password": session.hotspot_password,
            "profile": plan.mikrotik_profile,
            "limit-uptime": _ros_duration(plan.duration_seconds),
            # Enforce the plan's speed on the USER, so bandwidth is capped even if the
            # named profile on the router is misconfigured or missing. Belt and braces.
            "rate-limit": plan.rate_limit,
            # How many of the customer's devices may share this ONE account (and so its one
            # time+data budget): their phone plus the laptops/TV they add via tap-to-approve.
            "shared-users": str(plan.device_allowance),
            "comment": f"wifi.os session #{session.pk}",
        }
        if plan.data_cap_mb:
            payload["limit-bytes-total"] = str(plan.data_cap_mb * 1024 * 1024)
        try:
            with self._client() as client:
                existing = self._find_user_id(client, session.hotspot_username)
                if existing:
                    resp = client.patch(f"/ip/hotspot/user/{existing}", json=payload)
                else:
                    resp = client.put("/ip/hotspot/user", json=payload)
                resp.raise_for_status()
                return ProvisionResult(ok=True, message="activated", raw=resp.json())
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"activate_user failed on {self.router}: {exc}") from exc

    def suspend_user(self, session) -> ProvisionResult:
        try:
            with self._client() as client:
                # Kick the live session(s) first, then remove the credentials
                resp = client.get(
                    "/ip/hotspot/active", params={"user": session.hotspot_username}
                )
                resp.raise_for_status()
                for active in resp.json():
                    client.delete(f"/ip/hotspot/active/{active['.id']}").raise_for_status()
                user_id = self._find_user_id(client, session.hotspot_username)
                if user_id:
                    client.delete(f"/ip/hotspot/user/{user_id}").raise_for_status()
                return ProvisionResult(ok=True, message="suspended")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"suspend_user failed on {self.router}: {exc}") from exc

    def get_active_sessions(self) -> list[ActiveSession]:
        try:
            with self._client() as client:
                resp = client.get("/ip/hotspot/active")
                resp.raise_for_status()
                return [
                    ActiveSession(
                        username=a.get("user", ""),
                        mac_address=a.get("mac-address", ""),
                        ip_address=a.get("address", ""),
                        uptime=a.get("uptime", ""),
                        bytes_in=_to_int(a.get("bytes-in")),
                        bytes_out=_to_int(a.get("bytes-out")),
                    )
                    for a in resp.json()
                ]
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"get_active_sessions failed on {self.router}: {exc}") from exc

    def test_connection(self) -> bool:
        """True if reachable and authenticated. Raises ProvisioningAuthError when
        the router answers but rejects our credentials (wiped API user), so callers
        can distinguish 'offline' from 'needs re-onboarding'."""
        try:
            with self._client() as client:
                resp = client.get("/system/resource")
        except httpx.HTTPError:
            return False  # unreachable / offline — config is presumably intact
        if resp.status_code in (401, 403):
            raise ProvisioningAuthError(
                f"{self.router} rejected our API credentials (status {resp.status_code})"
            )
        return resp.status_code == 200

    # -- Multi-device sharing (tap-to-approve) ----------------------------
    def list_hosts(self) -> list[HostEntry]:
        """Devices the router currently sees on the hotspot LAN, named from DHCP leases.

        /ip/hotspot/host is the live table; a host is `authorized` once it has an
        associated hotspot user (it belongs to a paid session already). We join DHCP
        leases by MAC purely for a friendly name to show the customer.
        """
        try:
            with self._client() as client:
                resp = client.get("/ip/hotspot/host")
                resp.raise_for_status()
                hosts = resp.json()
                leases = client.get("/ip/dhcp-server/lease").json()
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"list_hosts failed on {self.router}: {exc}") from exc

        names = {
            (lease.get("mac-address") or "").upper(): lease.get("host-name", "")
            for lease in leases
        }
        out = []
        for h in hosts:
            mac = (h.get("mac-address") or "").upper()
            if not mac:
                continue
            out.append(
                HostEntry(
                    mac_address=mac,
                    ip_address=h.get("address", ""),
                    hostname=h.get("host-name") or names.get(mac, ""),
                    # A host tied to a user, or explicitly bypassed, is already "on".
                    authorized=bool(h.get("authorized") == "true" or h.get("bypassed") == "true"),
                )
            )
        return out

    def login_device(self, *, username, password, mac, ip="") -> ProvisionResult:
        """Log a MAC into the hotspot as `username`, so it joins that account's shared
        session. Uses the RouterOS hotspot login command.

        NOTE: the exact REST shape of the login command is validated against real hardware
        in the pilot (see docs); the call is isolated here so only this method changes if
        RouterOS wants a different field set.
        """
        payload = {"user": username, "password": password, "mac-address": mac.upper()}
        if ip:
            payload["ip"] = ip
        try:
            with self._client() as client:
                resp = client.post("/ip/hotspot/active/login", json=payload)
                resp.raise_for_status()
                return ProvisionResult(ok=True, message="device logged in", raw=_safe_json(resp))
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"login_device failed on {self.router}: {exc}") from exc

    def logout_device(self, mac) -> ProvisionResult:
        """Drop just this MAC's live session, leaving the account's other devices online."""
        mac = mac.upper()
        try:
            with self._client() as client:
                resp = client.get("/ip/hotspot/active", params={"mac-address": mac})
                resp.raise_for_status()
                for active in resp.json():
                    client.delete(f"/ip/hotspot/active/{active['.id']}").raise_for_status()
                return ProvisionResult(ok=True, message="device logged out")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"logout_device failed on {self.router}: {exc}") from exc

    # -- PPPoE ------------------------------------------------------------
    def _find_id(self, client_http, path: str, **params) -> str | None:
        resp = client_http.get(path, params=params)
        resp.raise_for_status()
        rows = resp.json()
        return rows[0][".id"] if rows else None

    def ensure_pppoe_profile(self, plan) -> ProvisionResult:
        payload = {
            "name": plan.mikrotik_profile,
            "rate-limit": plan.rate_limit,
            "only-one": "yes",
        }
        try:
            with self._client() as c:
                existing = self._find_id(c, "/ppp/profile", name=plan.mikrotik_profile)
                if existing:
                    c.patch(f"/ppp/profile/{existing}", json=payload).raise_for_status()
                else:
                    c.put("/ppp/profile", json=payload).raise_for_status()
            return ProvisionResult(ok=True, message="profile ensured")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"ensure_pppoe_profile failed on {self.router}: {exc}") from exc

    def create_pppoe_user(self, client) -> ProvisionResult:
        payload = {
            "name": client.pppoe_username,
            "password": client.pppoe_password,
            "service": "pppoe",
            "profile": client.plan.mikrotik_profile,
            "comment": f"wifi.os {client.account_number}",
        }
        if client.static_ip:
            payload["remote-address"] = client.static_ip
        try:
            with self._client() as c:
                existing = self._find_id(c, "/ppp/secret", name=client.pppoe_username)
                if existing:
                    c.patch(f"/ppp/secret/{existing}", json=payload).raise_for_status()
                else:
                    c.put("/ppp/secret", json=payload).raise_for_status()
            return ProvisionResult(ok=True, message="secret created")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"create_pppoe_user failed on {self.router}: {exc}") from exc

    def set_pppoe_enabled(self, client, enabled: bool) -> ProvisionResult:
        """Suspend = move to the suspended profile + kick the live session.
        Restore = move back to the plan profile."""
        profile = client.plan.mikrotik_profile if enabled else SUSPENDED_PROFILE
        try:
            with self._client() as c:
                sid = self._find_id(c, "/ppp/secret", name=client.pppoe_username)
                if sid:
                    c.patch(f"/ppp/secret/{sid}", json={"profile": profile}).raise_for_status()
                if not enabled:
                    aid = self._find_id(c, "/ppp/active", name=client.pppoe_username)
                    if aid:
                        c.delete(f"/ppp/active/{aid}").raise_for_status()
            return ProvisionResult(ok=True, message="enabled" if enabled else "suspended")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"set_pppoe_enabled failed on {self.router}: {exc}") from exc

    def remove_pppoe_user(self, client) -> ProvisionResult:
        try:
            with self._client() as c:
                aid = self._find_id(c, "/ppp/active", name=client.pppoe_username)
                if aid:
                    c.delete(f"/ppp/active/{aid}").raise_for_status()
                sid = self._find_id(c, "/ppp/secret", name=client.pppoe_username)
                if sid:
                    c.delete(f"/ppp/secret/{sid}").raise_for_status()
            return ProvisionResult(ok=True, message="removed")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"remove_pppoe_user failed on {self.router}: {exc}") from exc

    def get_active_pppoe(self) -> list[ActiveSession]:
        """Who is online, and how much they have moved THIS SESSION.

        Two bulk reads, joined by username — never one call per client:
          * /ppp/active  → presence, WAN IP, uptime, caller-id (the remote MAC)
          * /interface   → the dynamic `<pppoe-{username}>` interface's byte counters

        RouterOS counts from the ROUTER's side, so rx-byte is what the client UPLOADED and
        tx-byte is what it DOWNLOADED. We report bytes_in = download, bytes_out = upload.
        Both are session-relative and reset on reconnect; the metering service turns them
        into a cumulative monthly figure (see pppoe.metering).
        """
        try:
            with self._client() as c:
                active = c.get("/ppp/active")
                active.raise_for_status()
                # Interface counters. `.proplist` keeps the payload small on big routers.
                ifaces = c.get(
                    "/interface", params={".proplist": "name,rx-byte,tx-byte,running"}
                )
                ifaces.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"get_active_pppoe failed on {self.router}: {exc}") from exc

        # username -> (download_bytes, upload_bytes). The dynamic interface is named
        # "<pppoe-USERNAME>".
        counters: dict[str, tuple[int, int]] = {}
        for row in ifaces.json():
            name = row.get("name", "")
            if not name.startswith("<pppoe-") or not name.endswith(">"):
                continue
            username = name[len("<pppoe-"):-1]
            counters[username] = (_to_int(row.get("tx-byte")), _to_int(row.get("rx-byte")))

        sessions = []
        for a in active.json():
            username = a.get("name", "")
            down, up = counters.get(username, (0, 0))
            sessions.append(
                ActiveSession(
                    username=username,
                    mac_address=a.get("caller-id", ""),
                    ip_address=a.get("address", ""),
                    uptime=a.get("uptime", ""),
                    bytes_in=down,
                    bytes_out=up,
                )
            )
        return sessions

    def get_device_info(self) -> DeviceInfo:
        """Query the router's identity + live health. Stable fields are persisted
        by the caller; live metrics are shown but not stored."""
        try:
            with self._client() as client:
                res = client.get("/system/resource")
                if res.status_code in (401, 403):
                    raise ProvisioningAuthError(f"{self.router} rejected our API credentials")
                res.raise_for_status()
                res = res.json()
                try:
                    rb = client.get("/system/routerboard").json()
                except httpx.HTTPError:
                    rb = {}
                try:
                    ident = client.get("/system/identity").json()
                except httpx.HTTPError:
                    ident = {}
                try:
                    active = len(client.get("/ip/hotspot/active").json())
                except httpx.HTTPError:
                    active = None
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"device_info failed on {self.router}: {exc}") from exc

        # "7.16.2 (stable)" -> "7.16.2"
        version = str(res.get("version", "")).split(" ")[0]
        return DeviceInfo(
            routeros_version=version,
            board_name=rb.get("model") or res.get("board-name", ""),
            serial_number=rb.get("serial-number", ""),
            architecture=res.get("architecture-name", ""),
            identity_name=ident.get("name", ""),
            uptime=res.get("uptime", ""),
            cpu_load=_to_int(res.get("cpu-load")),
            free_memory=_to_int(res.get("free-memory")),
            total_memory=_to_int(res.get("total-memory")),
            active_users=active,
        )

    # -- Captive portal ----------------------------------------------------
    def push_portal(self, portal_url: str) -> ProvisionResult:
        """Repoint this router's captive portal at `portal_url`.

        Two things have to move together, and the ORDER matters:

          1. The walled garden must allow the new host FIRST. It is what lets an unpaid
             customer's phone reach the portal at all — flip the redirect before opening
             the gate and every customer hits a blocked page.
          2. Then the login page, whose redirect is what actually sends them there.

        The old walled-garden entry is left in place: it costs nothing, and removing it
        while other routers or in-flight phones still point at the old address would break
        exactly the people this grace period exists to protect. The next full re-onboard
        cleans it up.
        """
        host = portal_url.replace("https://", "").replace("http://", "").split("/")[0]
        redirect = (
            f"{portal_url.rstrip('/')}/?mac=$(mac-esc)&ip=$(ip)"
            f"&login=$(link-login-only-esc)&orig=$(link-orig-esc)&router={self.router.id}"
        )
        login_html = (
            '<html><head><meta http-equiv="refresh" content="0; url='
            f'{redirect}"></head><body>Loading payment page...</body></html>'
        )
        try:
            with self._client() as client:
                # 1. Gate open for the new host (idempotent — skip if already allowed).
                existing = client.get("/ip/hotspot/walled-garden", params={"dst-host": host})
                existing.raise_for_status()
                if not existing.json():
                    client.put(
                        "/ip/hotspot/walled-garden",
                        json={"dst-host": host, "action": "allow", "comment": "wifi.os portal"},
                    ).raise_for_status()

                # 2. Rewrite the login page.
                files = client.get("/file", params={"name": "hotspot/login.html"})
                files.raise_for_status()
                for existing_file in files.json():
                    client.delete(f"/file/{existing_file['.id']}").raise_for_status()
                client.put(
                    "/file",
                    json={"name": "hotspot/login.html", "contents": login_html},
                ).raise_for_status()

                return ProvisionResult(ok=True, message=f"portal -> {host}")
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"push_portal failed on {self.router}: {exc}") from exc
