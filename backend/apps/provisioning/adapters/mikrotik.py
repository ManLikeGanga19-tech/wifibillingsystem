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
    InterfaceRate,
    PppoeSecret,
    ProvisioningAdapter,
    ProvisioningAuthError,
    ProvisioningError,
    ProvisionResult,
    SpeedDiagnostics,
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

# Static clients have no login, so suspension works by IP: their address goes into this
# firewall address-list, which the ISP firewalls to the same walled-garden pay page (a
# one-time setup, exactly like the suspended PPPoE profile). Membership is all WIFI.OS touches.
SUSPENDED_ADDRESS_LIST = "wifios-suspended"

#: Marks our MSS-clamp rule so ensure_pppoe_mss_clamp is idempotent (never double-adds it).
MSS_CLAMP_COMMENT = "wifi.os: pppoe mss clamp"


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

    def ensure_hotspot_profile(self, plan) -> ProvisionResult:
        """Upsert the /ip/hotspot/user/profile carrying the plan's speed + device allowance.

        rate-limit and shared-users are PROFILE properties in RouterOS, not user ones — so
        this is where they belong. PATCH an existing profile (preserving whatever else the
        ISP set on it) or create it; the hotspot user then just names this profile.
        """
        payload = {
            "name": plan.mikrotik_profile,
            "rate-limit": plan.rate_limit,
            # Devices that may share ONE account at once: the paying phone plus the
            # laptops/TV added via tap-to-approve.
            "shared-users": str(plan.device_allowance),
        }
        try:
            with self._client() as client:
                existing = self._find_id(
                    client, "/ip/hotspot/user/profile", name=plan.mikrotik_profile
                )
                if existing:
                    resp = client.patch(f"/ip/hotspot/user/profile/{existing}", json=payload)
                else:
                    resp = client.put("/ip/hotspot/user/profile", json=payload)
                resp.raise_for_status()
                return ProvisionResult(ok=True, message="profile ensured", raw=_safe_json(resp))
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"ensure_hotspot_profile failed on {self.router}: {exc}"
            ) from exc

    def activate_user(self, session) -> ProvisionResult:
        plan = session.plan
        # Speed + device allowance live on the profile (RouterOS rejects them on the user),
        # so make sure the plan's profile carries them before we point the user at it.
        self.ensure_hotspot_profile(plan)
        payload = {
            "name": session.hotspot_username,
            "password": session.hotspot_password,
            "profile": plan.mikrotik_profile,
            "limit-uptime": _ros_duration(plan.duration_seconds),
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
                return ProvisionResult(ok=True, message="activated", raw=_safe_json(resp))
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
                # Idempotent: if the device is already authenticated, that IS the goal — the
                # router answers 400 "... is already logged in", which is a success for us, not
                # a failure to surface.
                if resp.status_code == 400 and "already logged in" in resp.text.lower():
                    return ProvisionResult(ok=True, message="already online")
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

    def _pppoe_addressing(self, client_http) -> dict:
        """The local-address (gateway) + remote-address (pool) a plan profile must carry.

        A PPP secret is authenticated against its OWN profile, and if that profile has no
        addressing the client comes up with no IP — authenticated but dead. Plan profiles
        the platform creates therefore have to carry addressing too. We READ it from the
        PPPoE server's default profile rather than hard-coding a pool, so this honours
        whatever the ISP set up and works unchanged on any router. Empty if the ISP uses a
        bridged/other scheme with no pool — we never invent one.
        """
        servers = client_http.get("/ppp/profile", params={"name": "pppoe-default"}).json()
        # Prefer the pppoe-server's declared default profile; fall back to `pppoe-default`.
        try:
            srv = client_http.get("/interface/pppoe-server/server").json()
            dp = srv[0].get("default-profile") if srv else None
            if dp:
                servers = client_http.get("/ppp/profile", params={"name": dp}).json()
        except (httpx.HTTPError, IndexError, KeyError):
            pass
        if not servers:
            return {}
        p = servers[0]
        return {
            k: p[k]
            for k in ("local-address", "remote-address")
            if p.get(k)
        }

    def ensure_pppoe_profile(self, plan) -> ProvisionResult:
        payload = {
            "name": plan.mikrotik_profile,
            "rate-limit": plan.rate_limit,
            "only-one": "yes",
        }
        try:
            with self._client() as c:
                # Carry the same pool + gateway the ISP's PPPoE server hands out, or an
                # authenticated client on this plan would get no IP.
                payload.update(self._pppoe_addressing(c))
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

    # -- Static IP -----------------------------------------------------------
    def _static_queue_name(self, client) -> str:
        return f"wifios-{client.account_number}"

    def ensure_static_queue(self, client) -> ProvisionResult:
        """The /queue/simple that enforces this static client's plan speed on their fixed IP.
        Idempotent: patched if it exists, created if not."""
        name = self._static_queue_name(client)
        payload = {
            "name": name,
            "target": f"{client.static_ip}/32",
            "max-limit": f"{client.plan.upload_kbps}k/{client.plan.download_kbps}k",
            "comment": f"wifi.os {client.account_number}",
        }
        try:
            with self._client() as c:
                existing = self._find_id(c, "/queue/simple", name=name)
                if existing:
                    c.patch(f"/queue/simple/{existing}", json=payload).raise_for_status()
                else:
                    c.put("/queue/simple", json=payload).raise_for_status()
            return ProvisionResult(ok=True, message="static queue ensured")
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"ensure_static_queue failed on {self.router}: {exc}"
            ) from exc

    def set_static_enabled(self, client, enabled: bool) -> ProvisionResult:
        """Suspend = put the IP in the suspended address-list (walled garden). Restore =
        take it out. The queue is left in place either way."""
        try:
            with self._client() as c:
                existing = self._find_id(
                    c, "/ip/firewall/address-list",
                    list=SUSPENDED_ADDRESS_LIST, address=client.static_ip,
                )
                if enabled and existing:
                    c.delete(f"/ip/firewall/address-list/{existing}").raise_for_status()
                elif not enabled and not existing:
                    c.put(
                        "/ip/firewall/address-list",
                        json={
                            "list": SUSPENDED_ADDRESS_LIST,
                            "address": client.static_ip,
                            "comment": f"wifi.os {client.account_number}",
                        },
                    ).raise_for_status()
            return ProvisionResult(ok=True, message="enabled" if enabled else "suspended")
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"set_static_enabled failed on {self.router}: {exc}"
            ) from exc

    def remove_static_queue(self, client) -> ProvisionResult:
        try:
            with self._client() as c:
                qid = self._find_id(c, "/queue/simple", name=self._static_queue_name(client))
                if qid:
                    c.delete(f"/queue/simple/{qid}").raise_for_status()
                aid = self._find_id(
                    c, "/ip/firewall/address-list",
                    list=SUSPENDED_ADDRESS_LIST, address=client.static_ip,
                )
                if aid:
                    c.delete(f"/ip/firewall/address-list/{aid}").raise_for_status()
            return ProvisionResult(ok=True, message="removed")
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"remove_static_queue failed on {self.router}: {exc}"
            ) from exc

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

    def list_pppoe_secrets(self) -> list[PppoeSecret]:
        """Read every PPPoE /ppp/secret off the router so an ISP can adopt pre-existing
        users into WIFI.OS. Password is stored plaintext on RouterOS, so an adopted client
        keeps its exact credentials and its live session is never disturbed."""
        try:
            with self._client() as c:
                resp = c.get(
                    "/ppp/secret",
                    params={".proplist": "name,password,profile,comment,service"},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"list_pppoe_secrets failed on {self.router}: {exc}"
            ) from exc
        secrets = []
        for row in resp.json():
            # service "any" also serves PPPoE; skip pure pptp/l2tp/etc. secrets.
            if row.get("service", "any") not in ("pppoe", "any", ""):
                continue
            username = row.get("name", "")
            if username:
                secrets.append(
                    PppoeSecret(
                        username=username,
                        password=row.get("password", ""),
                        profile=row.get("profile", ""),
                        comment=row.get("comment", ""),
                    )
                )
        return secrets

    def kick_pppoe_session(self, client) -> ProvisionResult:
        """Drop the live session so the CPE redials onto the (changed) profile immediately.
        Credentials are untouched, so the customer reconnects on their own within seconds."""
        try:
            with self._client() as c:
                aid = self._find_id(c, "/ppp/active", name=client.pppoe_username)
                if aid:
                    c.delete(f"/ppp/active/{aid}").raise_for_status()
            return ProvisionResult(ok=True, message="session kicked")
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"kick_pppoe_session failed on {self.router}: {exc}"
            ) from exc

    def ensure_pppoe_mss_clamp(self) -> ProvisionResult:
        """Add the forward-chain TCP-MSS clamp (clamp-to-pmtu) if it isn't already there.
        Idempotent via a WIFI.OS comment, so it's safe to call on every provision. One rule
        fixes the whole router — the classic PPPoE 'some sites are slow/half-load' problem."""
        rule = {
            "chain": "forward",
            "protocol": "tcp",
            "tcp-flags": "syn",
            "action": "change-mss",
            "new-mss": "clamp-to-pmtu",
            "passthrough": "yes",
            "comment": MSS_CLAMP_COMMENT,
        }
        try:
            with self._client() as c:
                existing = c.get(
                    "/ip/firewall/mangle", params={"comment": MSS_CLAMP_COMMENT}
                )
                existing.raise_for_status()
                if not existing.json():
                    c.put("/ip/firewall/mangle", json=rule).raise_for_status()
            return ProvisionResult(ok=True, message="mss clamp ensured")
        except httpx.HTTPError as exc:
            raise ProvisioningError(
                f"ensure_pppoe_mss_clamp failed on {self.router}: {exc}"
            ) from exc

    def get_speed_diagnostics(self) -> SpeedDiagnostics:
        """Read-only snapshot for the 'clients are slow' investigation. Each sub-read is
        isolated so a router that answers most calls but not one still returns what it can.
        Interface throughput is two counter reads ~1s apart — plain GETs, no streaming."""
        import time

        diag = SpeedDiagnostics()
        iface_props = {".proplist": "name,rx-byte,tx-byte,running"}
        try:
            with self._client() as c:
                res = c.get("/system/resource")
                if res.status_code in (401, 403):
                    raise ProvisioningAuthError(
                        f"{self.router} rejected our API credentials (status {res.status_code})"
                    )
                res.raise_for_status()
                r = res.json()
                diag.reachable = True
                diag.board_name = r.get("board-name", "")
                diag.uptime = r.get("uptime", "")
                diag.cpu_load = _to_int(r.get("cpu-load"))
                fm, tm = _to_int(r.get("free-memory")), _to_int(r.get("total-memory"))
                if fm is not None and tm:
                    diag.mem_used_pct = 100 - round(100 * fm / tm)

                # The MSS clamp — a missing one is the classic PPPoE slowness.
                try:
                    mangle = c.get("/ip/firewall/mangle", params={"comment": MSS_CLAMP_COMMENT})
                    mangle.raise_for_status()
                    diag.mss_clamp_present = bool(mangle.json())
                except httpx.HTTPError:
                    diag.notes.append("could not read the firewall mangle rules")

                # Simple-queue count — a double-limit (profile + leftover queue) shows here.
                try:
                    q = c.get("/queue/simple", params={".proplist": ".id"})
                    q.raise_for_status()
                    diag.simple_queue_count = len(q.json())
                except httpx.HTTPError:
                    diag.notes.append("could not read simple queues")

                try:
                    a = c.get("/ppp/active", params={".proplist": ".id"})
                    a.raise_for_status()
                    diag.pppoe_active_count = len(a.json())
                except httpx.HTTPError:
                    diag.notes.append("could not read PPPoE active sessions")

                # Live throughput: delta of the byte counters over ~1s → Mbps per interface.
                try:
                    r1 = c.get("/interface", params=iface_props).json()
                    time.sleep(1)
                    r2 = c.get("/interface", params=iface_props).json()
                    first = {r.get("name"): r for r in r1}
                    second = {r.get("name"): r for r in r2}
                    rates: list[InterfaceRate] = []
                    for name, s in second.items():
                        f = first.get(name)
                        # A dynamic per-client PPPoE interface is not the uplink; skip them.
                        if not f or name.startswith("<pppoe-") or s.get("running") != "true":
                            continue
                        rx0, rx1 = _to_int(f.get("rx-byte")), _to_int(s.get("rx-byte"))
                        tx0, tx1 = _to_int(f.get("tx-byte")), _to_int(s.get("tx-byte"))
                        if None in (rx0, rx1, tx0, tx1):
                            continue
                        rates.append(InterfaceRate(
                            name=name,
                            rx_mbps=round(max(0, rx1 - rx0) * 8 / 1_000_000, 2),
                            tx_mbps=round(max(0, tx1 - tx0) * 8 / 1_000_000, 2),
                        ))
                    rates.sort(key=lambda x: x.rx_mbps + x.tx_mbps, reverse=True)
                    diag.top_interfaces = rates[:5]
                except httpx.HTTPError:
                    diag.notes.append("could not read interface throughput")
        except ProvisioningAuthError:
            raise
        except httpx.HTTPError as exc:
            raise ProvisioningError(f"speed diagnostics failed on {self.router}: {exc}") from exc
        return diag

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
