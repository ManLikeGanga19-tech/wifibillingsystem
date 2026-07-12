"""C2B (paybill) handling for broadband payments on Danamo's shared shortcode.

The customer types their globally-unique account number as the M-Pesa account
reference (BillRefNumber); that routes the payment to the right ISP + client.
Idempotent on the M-Pesa TransID.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError
from django.db import transaction as db_transaction

from apps.core.services import audit

from .models import C2BPayment

logger = logging.getLogger(__name__)


def find_client(bill_ref: str):
    from apps.pppoe.models import Client

    return Client.objects.filter(account_number=(bill_ref or "").strip().upper()).first()


def process_c2b_confirmation(payload: dict) -> C2BPayment | None:
    """Safaricom C2B confirmation. Idempotent on TransID; stores raw payload;
    matches the account number to a client and records the payment."""
    trans_id = payload.get("TransID") or payload.get("TransactionID")
    if not trans_id:
        logger.warning("C2B without TransID: %s", payload)
        return None

    existing = C2BPayment.objects.filter(trans_id=trans_id).first()
    if existing:
        return existing  # replayed confirmation — no double credit

    bill_ref = payload.get("BillRefNumber", "")
    amount = Decimal(str(payload.get("TransAmount", "0") or "0"))
    client = find_client(bill_ref)

    from apps.billing.tariffs import collection_cost

    # THE MONEY GATE, on the way in. We cannot refuse a C2B payment — Safaricom has
    # already taken the customer's money by the time we hear about it. So when the
    # account belongs to an ISP that is not cleared to transact, we HOLD it:
    # recorded and attributed, but NOT credited to their wallet and NOT restoring
    # service. It is released the instant they go live (release_held_payments).
    held = bool(client) and not client.operator.can_transact
    if client:
        status = C2BPayment.Status.HELD if held else C2BPayment.Status.MATCHED
    else:
        status = C2BPayment.Status.UNMATCHED

    try:
        with db_transaction.atomic():
            payment = C2BPayment.objects.create(
                trans_id=trans_id,
                bill_ref=bill_ref,
                msisdn=str(payload.get("MSISDN", ""))[:15],
                amount=amount,
                first_name=str(payload.get("FirstName", ""))[:60],
                operator=client.operator if client else None,
                client=client,
                status=status,
                raw_payload=payload,
                platform_cost=collection_cost(amount),
            )
    except IntegrityError:
        # concurrent duplicate confirmation
        return C2BPayment.objects.filter(trans_id=trans_id).first()

    if held:
        logger.warning(
            "C2B %s: KSh %s HELD — %s is not cleared to transact",
            trans_id, amount, client.operator.slug,
        )
    elif client:
        from apps.pppoe.services import record_client_payment

        record_client_payment(client, amount, source="c2b", memo=f"M-Pesa {trans_id}")
    else:
        logger.warning("C2B %s: no client for account %r", trans_id, bill_ref)
    return payment


def release_held_payments(operator) -> int:
    """An ISP just went live. Everything their customers paid while they were being
    verified is credited now — nobody loses a shilling for our waiting.

    Idempotent: a payment can only leave HELD once, so re-running credits nothing
    twice.
    """
    from apps.pppoe.services import record_client_payment

    released = 0
    held = C2BPayment.objects.select_related("client").filter(
        operator=operator, status=C2BPayment.Status.HELD, client__isnull=False
    )
    for payment in held:
        with db_transaction.atomic():
            # Re-read under lock: two approvals racing must not double-credit.
            row = (
                C2BPayment.objects.select_for_update()
                .filter(pk=payment.pk, status=C2BPayment.Status.HELD)
                .first()
            )
            if row is None:
                continue
            row.status = C2BPayment.Status.MATCHED
            row.save(update_fields=["status"])
            record_client_payment(
                row.client, row.amount, source="c2b", memo=f"M-Pesa {row.trans_id} (released)"
            )
            released += 1
    if released:
        logger.info("Released %s held payment(s) for %s", released, operator.slug)
    return released


# ---- resolving unmatched payments --------------------------------------------------
#
# A customer pays their PPPoE bill by paybill and mistypes the account number. Safaricom
# has already taken the money, so we cannot refuse it — it lands UNMATCHED, attributed to
# nobody. Left alone, that is a customer who paid and stayed cut off, and an ISP short a
# payment they will be blamed for losing. This is the queue and the tools to fix it.


def suggest_clients_for(payment, limit: int = 5):
    """Rank the clients this misdirected payment most likely belongs to.

    Two signals, strongest first:
      1. The PAYER'S PHONE. M-Pesa tells us who paid; if that number is on a client's
         record, that is almost certainly them — a typo in the account number doesn't
         change who sent the money.
      2. A FUZZY match on the account number they typed. "ACME01" for "ACME001".

    Returns [(client, score 0..1, reason)], best first. Advisory only — a human still
    confirms; we are narrowing the haystack, not deciding.
    """
    import difflib

    from apps.pppoe.models import Client

    ref = (payment.bill_ref or "").strip().upper()
    msisdn = (payment.msisdn or "").strip()
    ranked: dict[int, tuple[float, str]] = {}

    def offer(client, score, reason):
        prev = ranked.get(client.id)
        if prev is None or score > prev[0]:
            ranked[client.id] = (score, reason)

    by_id: dict[int, Client] = {}

    # 1) payer phone — match on the last 9 digits (handles 2547…/07…/7… forms).
    if msisdn and len(msisdn) >= 9:
        for c in Client.objects.filter(phone__endswith=msisdn[-9:])[:10]:
            by_id[c.id] = c
            offer(c, 0.97, f"Paid from {msisdn}, which is on this client's record")

    # 2) fuzzy account number. Prefilter by the leading characters (account numbers are
    #    ISP-prefixed, e.g. ACME001), so we fuzzy-rank one ISP's clients, not everyone.
    if ref:
        prefix = ref[:3]
        pool = Client.objects.filter(account_number__istartswith=prefix)[:500]
        if not pool:
            pool = Client.objects.all()[:500]  # nothing shares the prefix — cast wider
        for c in pool:
            by_id[c.id] = c
            score = difflib.SequenceMatcher(None, ref, c.account_number.upper()).ratio()
            if score >= 0.6:
                offer(c, score, f"Account {c.account_number} resembles the '{ref}' they typed")

    best = sorted(ranked.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    return [(by_id[cid], score, reason) for cid, (score, reason) in best]


def resolve_unmatched_payment(payment, client, *, actor=None):
    """Assign a mis-sent C2B payment to the client it really belongs to, and credit it.

    Only for payments that were never correctly attributed (UNMATCHED). If the client's
    ISP is not yet cleared to transact the money is HELD, exactly as a correctly-typed
    payment would have been — resolution corrects the routing, it does not bypass the
    money gate.
    """
    from apps.pppoe.services import record_client_payment

    with db_transaction.atomic():
        row = C2BPayment.objects.select_for_update().get(pk=payment.pk)
        if row.status != C2BPayment.Status.UNMATCHED:
            raise ValueError("That payment has already been resolved.")

        held = not client.operator.can_transact
        row.client = client
        row.operator = client.operator
        row.status = C2BPayment.Status.HELD if held else C2BPayment.Status.MATCHED
        row.save(update_fields=["client", "operator", "status"])

        if not held:
            record_client_payment(
                client, row.amount, source="c2b-resolved",
                memo=f"M-Pesa {row.trans_id} (account was mistyped '{row.bill_ref}')",
            )

    audit(
        "c2b_payment_resolved",
        operator=client.operator,
        actor=actor,
        target=client,
        trans_id=row.trans_id,
        amount=str(row.amount),
        typed_account=row.bill_ref,
        held=held,
    )
    return row
