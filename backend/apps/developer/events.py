"""The catalog of platform events an ISP can forward to their own endpoint.

One source of truth: the settings UI lists these, the serializer validates against them, and
dispatch.emit_event refuses anything not here — so a typo can never silently subscribe to a
non-event. Add a row here (and an emit_event call at the lifecycle point) to ship a new event.
"""

WEBHOOK_EVENTS: list[tuple[str, str]] = [
    ("subscriber.created", "A fixed-line (PPPoE) subscriber was created"),
    ("subscriber.paused", "A subscriber was suspended"),
    ("subscriber.resumed", "A subscriber was reactivated"),
    ("payment.received", "A payment was received"),
    ("payment.refunded", "A payment was refunded"),
    ("voucher.generated", "A batch of vouchers was generated"),
    ("voucher.redeemed", "A voucher was redeemed"),
    ("ticket.opened", "A support ticket was opened"),
    ("ticket.resolved", "A support ticket was resolved"),
]

EVENT_KEYS: frozenset[str] = frozenset(k for k, _ in WEBHOOK_EVENTS)
