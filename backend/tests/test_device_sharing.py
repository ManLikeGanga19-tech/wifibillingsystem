"""Multi-device sharing: one payment, several of a customer's devices (tap-to-approve).

The parts that carry weight and get the hard tests:
  * ONE shared budget — the router account carries shared-users = the plan's allowance;
  * per-CATEGORY slots — a TV draws on tv_slots, never a phone's shared_users slot;
  * the token gate — only the paying device (holding device_token) can manage devices;
  * ROLLBACK — a router that refuses a login must not silently burn a slot;
  * idempotency — re-tapping a device is a no-op, not a second slot;
  * the paying device is auto-recorded, and cannot be removed.
"""

import pytest
from django.utils import timezone

from apps.provisioning import devices as dev
from apps.provisioning.adapters.dummy import DummyAdapter
from apps.provisioning.models import Session, SessionDevice

from .factories import PlanFactory, RouterFactory, SessionFactory

pytestmark = pytest.mark.django_db

DEVICES = "/api/v1/portal/devices/"


def a_session(*, shared_users=1, tv_slots=0, mac="AA:BB:CC:00:00:01"):
    router = RouterFactory(provisioning_backend="dummy")
    plan = PlanFactory(operator=router.operator, shared_users=shared_users, tv_slots=tv_slots)
    return SessionFactory(
        operator=router.operator, router=router, plan=plan,
        status=Session.Status.ACTIVE, mac_address=mac,
        hotspot_username="254700123123", hotspot_password="secret",
    )


# --- allowance & the plan ---------------------------------------------------------------


def test_device_allowance_is_general_plus_tv():
    plan = PlanFactory(shared_users=3, tv_slots=1)
    assert plan.device_allowance == 4


def test_activation_puts_shared_users_on_the_profile_not_the_user():
    """RouterOS rejects rate-limit/shared-users on the hotspot USER — they belong on the
    PROFILE. So activation must upsert the profile with shared-users = allowance, and the
    user payload must NOT carry shared-users (that was a real 400-on-every-activation bug)."""
    from apps.provisioning.adapters.mikrotik import MikroTikRestAdapter

    session = a_session(shared_users=3, tv_slots=1)
    profile_payload = {}
    user_payload = {}

    class FakeResp:
        def raise_for_status(self): ...
        def json(self):
            return {}

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, *a, **k):
            return _Empty()
        def _capture(self, path, json):
            (profile_payload if "profile" in path else user_payload).update(json or {})
            return FakeResp()
        def put(self, path, json=None):
            return self._capture(path, json)
        def patch(self, path, json=None):
            return self._capture(path, json)

    class _Empty:
        def raise_for_status(self): ...
        def json(self):
            return []

    adapter = MikroTikRestAdapter(session.router)
    adapter._client = lambda: FakeClient()
    adapter.activate_user(session)
    # allowance = 3 + 1 = 4, on the PROFILE
    assert profile_payload["shared-users"] == "4"
    assert profile_payload["rate-limit"]  # speed lives on the profile too
    # ...and NOT on the user (which is what RouterOS 400'd on)
    assert "shared-users" not in user_payload
    assert "rate-limit" not in user_payload


# --- discovery --------------------------------------------------------------------------


def test_discovery_hides_authorized_and_already_added_devices():
    session = a_session(shared_users=3)
    dev.record_paying_device(session)  # the paying phone is on the session
    DummyAdapter.hosts = {
        "AA:BB:CC:00:00:01": ("10.5.0.2", "paying-phone", False),  # already ours
        "AA:BB:CC:00:00:02": ("10.5.0.3", "her-laptop", False),  # addable
        "AA:BB:CC:00:00:99": ("10.5.0.9", "someone-else", True),  # already authorised
    }
    found = {d["mac_address"] for d in dev.discover_devices(session)}
    assert found == {"AA:BB:CC:00:00:02"}


def test_discovery_on_an_unreachable_router_is_empty_not_an_error():
    session = a_session()
    from apps.provisioning import adapters

    class Boom:
        def list_hosts(self):
            from apps.provisioning.adapters import ProvisioningError

            raise ProvisioningError("down")

    orig = adapters.get_adapter
    adapters.get_adapter = lambda r: Boom()
    try:
        assert dev.discover_devices(session) == []
    finally:
        adapters.get_adapter = orig


# --- approving --------------------------------------------------------------------------


def test_approving_logs_the_device_in_and_records_it():
    session = a_session(shared_users=3)
    DummyAdapter.hosts = {"AA:BB:CC:00:00:02": ("10.5.0.3", "laptop", False)}

    d = dev.approve_device(session, "aabbcc000002", kind="laptop")
    assert d.mac_address == "AA:BB:CC:00:00:02"
    assert ("login_device", "AA:BB:CC:00:00:02", "254700123123") in DummyAdapter.calls
    assert "AA:BB:CC:00:00:02" in DummyAdapter.logged_in


def test_re_approving_the_same_device_is_idempotent():
    session = a_session(shared_users=3)
    dev.approve_device(session, "AA:BB:CC:00:00:02", kind="laptop")
    before = SessionDevice.objects.filter(session=session).count()
    dev.approve_device(session, "aa:bb:cc:00:00:02", kind="laptop")  # same MAC, any format
    assert SessionDevice.objects.filter(session=session).count() == before


def test_a_full_general_allowance_is_refused():
    session = a_session(shared_users=1)
    dev.record_paying_device(session)  # the one general slot is taken by the payer
    with pytest.raises(dev.DeviceError):
        dev.approve_device(session, "AA:BB:CC:00:00:07", kind="phone")


def test_a_tv_uses_its_own_slot_not_a_phone_slot():
    session = a_session(shared_users=1, tv_slots=1)
    dev.record_paying_device(session)  # fills the single general slot
    # A phone would be refused...
    with pytest.raises(dev.DeviceError):
        dev.approve_device(session, "AA:BB:CC:00:00:08", kind="phone")
    # ...but the TV has its own dedicated slot.
    tv = dev.approve_device(session, "AA:BB:CC:00:00:09", kind="tv")
    assert tv.kind == "tv"
    assert session.tv_devices_used() == 1


def test_login_device_treats_already_logged_in_as_success():
    """RouterOS answers 400 '... is already logged in' when the device is ALREADY online —
    which is exactly the goal, not a failure. login_device must return ok, so a reconnect of
    an already-connected customer doesn't error."""
    from apps.provisioning.adapters.mikrotik import MikroTikRestAdapter

    session = a_session()

    class Resp:
        status_code = 400
        text = '{"detail":"IP 10.5.50.254 is already logged in","error":400}'

        def raise_for_status(self):
            raise AssertionError("should not reach raise_for_status for already-logged-in")

        def json(self):
            return {}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, path, json=None):
            return Resp()

    adapter = MikroTikRestAdapter(session.router)
    adapter._client = lambda: FakeClient()
    result = adapter.login_device(username="u", password="p", mac="AA:BB:CC:DD:EE:FF")
    assert result.ok is True


def test_a_router_that_refuses_the_login_rolls_the_slot_back():
    from apps.provisioning.adapters import ProvisioningError

    session = a_session(shared_users=2)
    DummyAdapter.login_fails = True
    with pytest.raises(ProvisioningError):
        dev.approve_device(session, "AA:BB:CC:00:00:0A", kind="laptop")
    # The record must NOT survive a failed push — the slot is free again.
    assert SessionDevice.objects.filter(session=session).count() == 0


# --- removing ---------------------------------------------------------------------------


def test_removing_logs_the_device_out_and_frees_the_slot():
    session = a_session(shared_users=3)
    dev.approve_device(session, "AA:BB:CC:00:00:02", kind="laptop")
    dev.remove_device(session, "AA:BB:CC:00:00:02")
    assert SessionDevice.objects.filter(session=session).count() == 0
    assert ("logout_device", "AA:BB:CC:00:00:02") in DummyAdapter.calls


def test_the_paying_device_cannot_be_removed():
    session = a_session(shared_users=3)
    payer = dev.record_paying_device(session)
    with pytest.raises(dev.DeviceError):
        dev.remove_device(session, payer.mac_address)


# --- the token gate (API) ---------------------------------------------------------------


def test_the_api_needs_a_valid_token(api_client):
    a_session(shared_users=3)  # a real session exists; the 404s are purely the token gate
    # No token / wrong token -> 404, never a hint about which.
    assert api_client.get(DEVICES).status_code == 404
    assert api_client.get(DEVICES, {"token": "nope"}).status_code == 404


def test_the_api_lists_slots_and_available_devices(api_client):
    session = a_session(shared_users=3, tv_slots=1)
    dev.record_paying_device(session)
    DummyAdapter.hosts = {"AA:BB:CC:00:00:02": ("10.5.0.3", "laptop", False)}

    body = api_client.get(DEVICES, {"token": session.device_token}).json()
    assert body["allowance"] == {"general": 3, "tv": 1}
    assert body["used"]["general"] == 1
    assert body["devices"][0]["is_paying_device"] is True
    assert body["available"][0]["mac_address"] == "AA:BB:CC:00:00:02"


def test_the_api_adds_and_removes_a_device(api_client):
    session = a_session(shared_users=3)
    DummyAdapter.hosts = {"AA:BB:CC:00:00:02": ("10.5.0.3", "laptop", False)}

    add = api_client.post(
        DEVICES,
        {"token": session.device_token, "mac": "AA:BB:CC:00:00:02", "kind": "laptop"},
        format="json",
    )
    assert add.status_code == 201
    assert any(d["mac_address"] == "AA:BB:CC:00:00:02" for d in add.json()["devices"])

    rm = api_client.delete(
        f"{DEVICES}?token={session.device_token}&mac=AA:BB:CC:00:00:02"
    )
    assert rm.status_code == 200
    assert SessionDevice.objects.filter(session=session).count() == 0


def test_an_expired_session_token_stops_working(api_client):
    session = a_session(shared_users=3)
    Session.objects.filter(pk=session.pk).update(
        expires_at=timezone.now() - timezone.timedelta(minutes=1)
    )
    assert api_client.get(DEVICES, {"token": session.device_token}).status_code == 404


def test_activation_records_and_logs_in_the_paying_device():
    """Going through the real activate() path must (1) list the paying phone as device #1
    (un-removable general slot) AND (2) actually LOG IT IN — creating the account is not
    enough; the device has to be authenticated to the hotspot or the dashboard says
    'online' while the customer has no internet (the exact bug reconnect hit)."""
    from apps.provisioning.services import activate

    session = a_session(shared_users=3, mac="AA:BB:CC:DD:EE:01")
    session.status = Session.Status.PENDING
    session.save(update_fields=["status"])
    activate(session)

    payer = SessionDevice.objects.get(session=session, is_paying_device=True)
    assert payer.mac_address == "AA:BB:CC:DD:EE:01"
    assert payer.kind == SessionDevice.Kind.PHONE
    # The device was pushed online, not just recorded.
    assert ("login_device", "AA:BB:CC:DD:EE:01", session.hotspot_username) in DummyAdapter.calls
    # And activation upserted the profile (where shared-users/rate-limit belong).
    assert any(c[0] == "ensure_hotspot_profile" for c in DummyAdapter.calls)


def test_devices_state_carries_a_session_summary(api_client):
    """The recovery view (magic link / URL) needs 'online until X' without a second call."""
    session = a_session(shared_users=3)
    body = api_client.get(DEVICES, {"token": session.device_token}).json()
    assert body["session"]["username"] == session.hotspot_username
    assert body["session"]["expires_at"]


# --- closed-the-tab recovery (SMS) ------------------------------------------------------

RECOVER = "/api/v1/portal/devices/recover/"


def test_recover_texts_a_link_to_the_paying_phone(api_client):
    from apps.notifications.models import Message

    session = a_session(shared_users=3)  # hotspot_username is the phone (M-Pesa)
    resp = api_client.post(
        RECOVER, {"phone": session.hotspot_username, "router": session.router.id}, format="json"
    )
    assert resp.status_code == 200
    msg = Message.objects.filter(to_phone=session.hotspot_username).first()
    assert msg is not None
    # The link carries the token — the capability that unlocks their add-devices screen.
    assert session.device_token in msg.body


def test_recover_is_generic_and_silent_for_a_phone_with_no_session(api_client):
    """Same 200 whether or not a plan exists (no enumeration), and no SMS goes out."""
    from apps.notifications.models import Message

    session = a_session(shared_users=3)
    resp = api_client.post(
        RECOVER, {"phone": "254799999999", "router": session.router.id}, format="json"
    )
    assert resp.status_code == 200
    assert not Message.objects.filter(to_phone="254799999999").exists()


def test_device_management_is_tenant_isolated():
    """A device row is stamped with the session's operator, so it can never leak across
    tenants even though the endpoint is public."""
    session = a_session(shared_users=3)
    d = dev.approve_device(session, "AA:BB:CC:00:00:02", kind="laptop")
    assert d.operator_id == session.operator_id
