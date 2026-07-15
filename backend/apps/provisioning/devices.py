"""Multi-device sharing: one paid session, several of a customer's devices.

The customer pays on one phone; this is how their other devices — a laptop, the TV — join
that SAME paid session, without a second payment. Every device logs into the hotspot as the
session's single account (which carries shared-users = the plan's allowance), so they share
one time+data budget. These functions are the safe middle: they enforce the per-category
allowance, keep our record in step with the router, and never leave a slot consumed by a
device the router refused.

Authorisation lives one layer up (the API gates every call on the session's device_token,
the secret only the paying device holds), so a stranger on the same open hotspot can never
add themselves to a session they did not pay for.
"""

import logging
import re

from django.db import transaction
from django.utils import timezone

from .adapters import ProvisioningError, get_adapter
from .models import Session, SessionDevice

logger = logging.getLogger(__name__)


class DeviceError(Exception):
    """Something the customer can understand and act on (slot full, unknown device).
    Safe to show."""


_HEX2 = re.compile(r"^[0-9A-F]{2}$")


def normalize_mac(raw: str) -> str:
    """Canonicalise a MAC to AA:BB:CC:DD:EE:FF. Raises DeviceError on anything that isn't
    one — this value is compared against the router's host table and stored, so it must be
    exactly a MAC and nothing that could confuse either."""
    hexed = re.sub(r"[^0-9A-Fa-f]", "", raw or "").upper()
    if len(hexed) != 12:
        raise DeviceError("That doesn't look like a device address.")
    pairs = [hexed[i : i + 2] for i in range(0, 12, 2)]
    return ":".join(pairs)


def session_for_token(token: str) -> Session | None:
    """The live session a device_token unlocks — active and still inside its window.
    Anything else (expired, suspended, unknown token) returns None, so the API answers a
    flat 'not found' without leaking which case it was."""
    if not token:
        return None
    session = (
        Session.objects.select_related("plan", "router", "operator")
        .filter(device_token=token, status=Session.Status.ACTIVE)
        .first()
    )
    if session is None:
        return None
    if session.clock_started and session.expires_at <= timezone.now():
        return None
    return session


def record_paying_device(session: Session) -> SessionDevice | None:
    """Register the device that paid as the first device on the session — automatically,
    holding a general slot, and un-removable. Idempotent, and a no-op when we don't know
    its MAC (some captive setups don't pass one)."""
    mac = (session.mac_address or "").strip()
    if not mac:
        return None
    try:
        mac = normalize_mac(mac)
    except DeviceError:
        return None
    device, _ = SessionDevice.objects.get_or_create(
        session=session,
        mac_address=mac,
        defaults={
            "operator": session.operator,
            "kind": SessionDevice.Kind.PHONE,
            "is_paying_device": True,
        },
    )
    return device


def discover_devices(session: Session) -> list[dict]:
    """Devices currently on the hotspot that the customer could add — from the router's
    live host table, minus the ones already on this session and any already authorised
    (they belong to a paid session, possibly someone else's). Best-effort: an unreachable
    router yields an empty list, not an error, so the picker degrades to 'none found'."""
    try:
        hosts = get_adapter(session.router).list_hosts()
    except ProvisioningError:
        logger.warning("discover_devices: %s unreachable", session.router.name)
        return []

    mine = set(session.devices.values_list("mac_address", flat=True))
    out = []
    for h in hosts:
        mac = (h.mac_address or "").upper()
        if not mac or mac in mine or h.authorized:
            continue
        out.append({"mac_address": mac, "hostname": h.hostname})
    return out


def _slot_check(session: Session, kind: str) -> None:
    """Raise if the relevant category is full. TV devices draw on the dedicated tv_slots;
    everything else on the plan's shared_users."""
    if kind == SessionDevice.Kind.TV:
        if session.tv_devices_used() >= session.tv_slots:
            raise DeviceError(
                "This plan has no TV slot left. Choose a plan that includes a TV to add one."
                if session.tv_slots == 0
                else "Your TV slot is already in use."
            )
    else:
        if session.general_devices_used() >= session.general_slots:
            raise DeviceError(
                f"You've reached this plan's {session.general_slots} device(s). "
                "Remove one first, or choose a plan with more devices."
            )


def approve_device(
    session: Session, raw_mac: str, *, kind: str = SessionDevice.Kind.OTHER, hostname: str = ""
) -> SessionDevice:
    """Put one of the customer's devices onto their paid session.

    Adding a device is: check the category's slot, record it, and log its MAC into the
    hotspot as the session's account. We do the record + router push under a row lock on
    the session and roll BOTH back if the router refuses — so a failed add never silently
    burns a slot, and two taps racing for the last slot can't both win.
    """
    mac = normalize_mac(raw_mac)
    if kind not in SessionDevice.Kind.values:
        kind = SessionDevice.Kind.OTHER

    # Already on this session? Idempotent — re-tapping is not an error, and doesn't consume
    # a second slot.
    existing = session.devices.filter(mac_address=mac).first()
    if existing:
        return existing

    # Find the device's current IP from the host table (the login wants it). Best-effort.
    ip = ""
    try:
        for h in get_adapter(session.router).list_hosts():
            if (h.mac_address or "").upper() == mac:
                ip = h.ip_address
                hostname = hostname or h.hostname
                break
    except ProvisioningError:
        pass

    with transaction.atomic():
        locked = Session.objects.select_for_update().get(pk=session.pk)
        # Re-check the slot under the lock (another tap may have just taken it).
        if session.devices.filter(mac_address=mac).exists():
            return session.devices.get(mac_address=mac)
        _slot_check(locked, kind)
        device = SessionDevice.objects.create(
            operator=session.operator,
            session=locked,
            mac_address=mac,
            hostname=hostname[:80],
            kind=kind,
        )
        # Push to the router INSIDE the transaction: if it raises, the row rolls back and
        # the slot is free again.
        get_adapter(session.router).login_device(
            username=session.hotspot_username,
            password=session.hotspot_password,
            mac=mac,
            ip=ip,
        )
    logger.info("Approved device %s (%s) onto session #%s", mac, kind, session.pk)
    return device


def remove_device(session: Session, raw_mac: str) -> None:
    """Take a device off the session and drop its live connection. The paying device can't
    be removed — it is the session's anchor."""
    mac = normalize_mac(raw_mac)
    device = session.devices.filter(mac_address=mac).first()
    if device is None:
        return  # already gone — nothing to do
    if device.is_paying_device:
        raise DeviceError("The device that paid can't be removed from its own plan.")

    # Drop the router session first, then our record — a failed logout leaves the record so
    # the customer can retry, rather than us claiming it's gone while it's still online.
    get_adapter(session.router).logout_device(mac)
    device.delete()
    logger.info("Removed device %s from session #%s", mac, session.pk)
