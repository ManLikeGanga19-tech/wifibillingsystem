"""A PPPoE plan profile must carry addressing, or an authenticated client gets no IP.

This was a real bug caught on the pilot RB951: `ensure_pppoe_profile` created a plan
profile with only the rate-limit, so a subscriber authenticated against it and then came
up with no address — a dead line. The fix copies the pool + gateway from the PPPoE
server's default profile onto every plan profile. These tests pin that behaviour against a
mocked RouterOS REST surface (no real router needed).
"""

import json

import httpx

from apps.provisioning.adapters.mikrotik import MikroTikRestAdapter


class _Plan:
    mikrotik_profile = "plan-home-8m"
    rate_limit = "4096k/8192k"


def _adapter_with(monkeypatch, handler) -> MikroTikRestAdapter:
    """A MikroTikRestAdapter whose HTTP client talks to `handler`, not a real router."""
    adapter = MikroTikRestAdapter(router=object())
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(base_url="http://router", transport=httpx.MockTransport(handler)),
    )
    return adapter


def test_plan_profile_inherits_pool_and_gateway(monkeypatch):
    """The plan profile PUT carries the default profile's local + remote address."""
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/interface/pppoe-server/server":
            return httpx.Response(200, json=[{".id": "*1", "default-profile": "pppoe-default"}])
        if path == "/ppp/profile" and method == "GET":
            name = request.url.params.get("name")
            if name == "pppoe-default":
                return httpx.Response(
                    200,
                    json=[{
                        ".id": "*2", "name": "pppoe-default",
                        "local-address": "10.6.0.1", "remote-address": "pppoe-pool",
                    }],
                )
            return httpx.Response(200, json=[])  # plan profile not yet there -> PUT path
        if path == "/ppp/profile" and method == "PUT":
            sent.update(json.loads(request.content))
            return httpx.Response(201, json={".id": "*3"})
        return httpx.Response(200, json=[])

    _adapter_with(monkeypatch, handler).ensure_pppoe_profile(_Plan())

    assert sent["local-address"] == "10.6.0.1"
    assert sent["remote-address"] == "pppoe-pool"
    assert sent["rate-limit"] == "4096k/8192k"


def test_no_pool_means_no_invented_addressing(monkeypatch):
    """If the ISP runs no pool on the default profile, we don't fabricate one."""
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/interface/pppoe-server/server":
            return httpx.Response(200, json=[{".id": "*1", "default-profile": "pppoe-default"}])
        if path == "/ppp/profile" and method == "GET":
            if request.url.params.get("name") == "pppoe-default":
                return httpx.Response(200, json=[{".id": "*2", "name": "pppoe-default"}])
            return httpx.Response(200, json=[])
        if path == "/ppp/profile" and method == "PUT":
            sent.update(json.loads(request.content))
            return httpx.Response(201, json={".id": "*3"})
        return httpx.Response(200, json=[])

    _adapter_with(monkeypatch, handler).ensure_pppoe_profile(_Plan())

    assert "local-address" not in sent
    assert "remote-address" not in sent
