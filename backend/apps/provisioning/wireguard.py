"""WireGuard identity for a router: keypair generation + overlay-IP allocation.

This is the foundation of the management plane (docs/WIREGUARD_MANAGEMENT_PLANE.md). It is
deliberately hub-agnostic: it mints the cryptographic identity and the /32 a router will
hold on the overlay, all deterministically and testably, without needing a live hub. The
enrollment flow and the hub reconciler build on top of it.

Security invariants enforced here:
  * The PRIVATE key never leaves this process except into a Fernet-encrypted column, and
    (once) into the setup script streamed over TLS. It is never logged.
  * Two routers can never hold the same /32 — the DB unique constraint is the backstop, and
    allocation always picks the lowest free host, skipping the hub address.
"""

import base64
import ipaddress

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from django.conf import settings
from django.db import IntegrityError, transaction


class OverlayExhausted(Exception):
    """No free /32 left in WG_OVERLAY_CIDR. A /16 is ~65k routers; alert well before this."""


def generate_keypair() -> tuple[str, str]:
    """A fresh Curve25519 keypair as (private_b64, public_b64) in WireGuard's wire format."""
    private = X25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(private_raw).decode(), base64.b64encode(public_raw).decode()


def _free_overlay_ip(used: set[str]) -> str:
    """Lowest host in the overlay CIDR that is not the hub and not already assigned."""
    network = ipaddress.ip_network(settings.WG_OVERLAY_CIDR)
    hub = ipaddress.ip_address(settings.WG_HUB_IP)
    for host in network.hosts():
        candidate = str(host)
        if host != hub and candidate not in used:
            return candidate
    raise OverlayExhausted(f"No free overlay IP in {settings.WG_OVERLAY_CIDR}")


def ensure_wireguard_identity(router) -> bool:
    """Idempotently give a router a keypair + overlay IP. Returns True if anything changed.

    Safe to call repeatedly (re-enrollment, reconciliation): a router that already has an
    identity is left untouched. The overlay-IP assignment retries on the (rare) race where
    two concurrent enrolments pick the same /32 — the DB unique constraint decides the
    winner, and the loser simply picks the next free address.
    """
    from .models import Router

    if router.wg_private_key and router.overlay_ip:
        return False

    for _attempt in range(5):
        changed: list[str] = []
        if not router.wg_private_key:
            private, public = generate_keypair()
            router.wg_private_key = private
            router.wg_public_key = public
            changed += ["wg_private_key", "wg_public_key"]
        if not router.overlay_ip:
            used = set(
                Router.objects.exclude(overlay_ip__isnull=True).values_list(
                    "overlay_ip", flat=True
                )
            )
            router.overlay_ip = _free_overlay_ip(used)
            changed.append("overlay_ip")
        try:
            with transaction.atomic():
                router.save(update_fields=[*changed, "updated_at"])
            return True
        except IntegrityError:
            # Another enrolment grabbed this /32 first. Drop it and try the next free one.
            router.overlay_ip = None
    raise OverlayExhausted("Could not allocate a unique overlay IP after several attempts")
