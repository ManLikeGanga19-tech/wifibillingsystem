import secrets
import uuid

from django.db import transaction as db_transaction

from apps.core.services import audit

from .models import Voucher

# No 0/O/1/I — codes get read from paper cards over the phone
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 8


class VoucherError(Exception):
    pass


def _generate_code(prefix: str = "") -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{prefix}{body}"[:20].upper()


def generate_batch(*, operator, plan, count: int, prefix: str = "", created_by=None):
    batch_id = uuid.uuid4()
    vouchers = []
    for _ in range(count):
        # Retry on the (astronomically unlikely) code collision
        for _attempt in range(5):
            code = _generate_code(prefix)
            if not Voucher.objects.filter(code=code).exists():
                break
        vouchers.append(
            Voucher(
                operator=operator, plan=plan, code=code, batch_id=batch_id, created_by=created_by
            )
        )
    created = Voucher.objects.bulk_create(vouchers)
    audit(
        "voucher_batch_generated",
        operator=operator,
        actor=created_by,
        count=count,
        plan=plan.name,
        batch_id=str(batch_id),
    )
    return created


def redeem(*, code: str, mac: str = "", router=None):
    """Single-use redemption. Row lock prevents two devices redeeming the same
    code concurrently; returns the created session."""
    from apps.provisioning.services import create_session_for_voucher
    from apps.provisioning.tasks import activate_session

    with db_transaction.atomic():
        voucher = (
            Voucher.objects.select_for_update()
            .select_related("plan", "operator")
            .filter(code=code.strip().upper())
            .first()
        )
        if voucher is None:
            raise VoucherError("Invalid voucher code")
        if voucher.status != Voucher.Status.UNUSED:
            raise VoucherError(f"Voucher already {voucher.status}")
        # The money gate. A voucher is prepaid service — honouring one for an ISP we
        # have not verified means putting a customer on the network for a business
        # we cannot yet pay out to. Enforced HERE, in the service, so every caller
        # is covered rather than just the one view.
        if not voucher.operator.can_transact:
            raise VoucherError("This WiFi hotspot is not live yet. Please try again later.")

        from django.utils import timezone

        voucher.status = Voucher.Status.REDEEMED
        voucher.redeemed_at = timezone.now()
        voucher.save(update_fields=["status", "redeemed_at", "updated_at"])

        session = create_session_for_voucher(voucher, mac=mac, router=router)
        audit("voucher_redeemed", operator=voucher.operator, target=voucher, mac=mac)
        db_transaction.on_commit(lambda: activate_session.delay(session.pk))
    return session
