"""RouterOS v7 REST API adapter.

Uses /ip/hotspot/user for credentials and /ip/hotspot/active for live sessions.
limit-uptime is set on the hotspot user so the router enforces cutoff even if
this server is unreachable at expiry time (belt and braces with expire_sessions).
"""

import logging

import httpx

from .base import (
    ActiveSession,
    ProvisioningAdapter,
    ProvisioningAuthError,
    ProvisioningError,
    ProvisionResult,
)

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
