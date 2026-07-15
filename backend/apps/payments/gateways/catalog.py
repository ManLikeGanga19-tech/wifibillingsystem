"""The payment gateways an ISP can collect through, declared once.

Single source of truth for the console (which renders a card per entry and a form from
`fields`) and the payment path (which builds an adapter from the stored credentials).

TWO KINDS, and the difference is the whole finance refactor:

  * WIFI.OS paybill (`wifios`) — money lands on OUR paybill. We withhold 3% at source and
    the ISP withdraws the rest from their wallet. Zero setup, works on day one. This is
    what lets a new ISP sell while Safaricom takes weeks to approve their own shortcode.

  * Everything else — money lands in the ISP's OWN account, instantly. We never touch it,
    so we cannot withhold anything: the fee is accrued to their platform account and
    invoiced (phase 4). `settlement = direct` is what stops that sale from ever becoming
    withdrawable from us.

DELIBERATELY ABSENT: "M-Pesa paybill/till WITHOUT API keys". The only way those can work is
an app forwarding M-Pesa SMS off a phone, and an SMS is trivially forgeable — it would put
a free-WiFi exploit inside a billing system. It needs its own decision about safeguards
(sender validation, receipt-code uniqueness, amount and freshness matching), not a
quiet addition to this list.
"""

from dataclasses import dataclass, field

PLATFORM = "platform"
DIRECT = "direct"


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    secret: bool = False
    placeholder: str = ""
    required: bool = True
    help: str = ""
    #: Renders as a picker rather than a text box.
    choices: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Gateway:
    id: str
    name: str
    #: Shown under the name — where this is a sensible choice.
    region: str
    #: What the customer can pay with. Chips on the card.
    methods: tuple[str, ...] = ()
    #: How fast the ISP sees the money. The reason an ISP switches at all.
    settles: str = ""
    settlement: str = DIRECT
    fields: list[Field] = field(default_factory=list)
    managed: bool = False
    note: str = ""
    #: Not yet implemented — shown, but honestly greyed out rather than pretending.
    available: bool = True


GATEWAYS: list[Gateway] = [
    Gateway(
        id="wifios",
        name="WIFI.OS Paybill",
        region="Kenya · managed by us",
        methods=("STK", "Paybill", "Instant"),
        settles="To your WIFI.OS wallet",
        settlement=PLATFORM,
        managed=True,
        note=(
            "Nothing to set up — start selling today. Customers pay our paybill, we take "
            "our 3% at source, and you withdraw the rest whenever you like. Switch to your "
            "own M-Pesa shortcode once Safaricom has approved it."
        ),
    ),
    Gateway(
        id="mpesa",
        name="M-Pesa (Daraja)",
        region="M-Pesa · Kenya",
        methods=("STK", "Paybill", "Till", "Instant"),
        settles="Straight to your own M-Pesa",
        settlement=DIRECT,
        note=(
            "Your own paybill or till, with your Daraja API keys. Customers' money reaches "
            "you instantly — we never touch it. Our fee is invoiced monthly instead."
        ),
        fields=[
            Field(
                "collection_method",
                "Collection method",
                choices=(("paybill", "Paybill"), ("till", "Till (Buy Goods)")),
                help=(
                    "Paybill — the customer pays your paybill and enters an account number. "
                    "Till — the customer pays your till (Buy Goods)."
                ),
            ),
            Field(
                "shortcode",
                "Paybill / Till number",
                placeholder="e.g. 545500",
                help="Your M-Pesa shortcode — the same one used for Daraja STK.",
            ),
            Field("consumer_key", "Consumer key", secret=True),
            Field("consumer_secret", "Consumer secret", secret=True),
            Field(
                "passkey",
                "Passkey",
                secret=True,
                help="For STK push — usually emailed to the address registered in Daraja.",
            ),
        ],
    ),
    # --- Phase 5. Listed so the ISP can see what is coming, but honestly marked. -------
    Gateway(
        id="kopokopo",
        name="Kopo Kopo",
        region="Kopo Kopo · Kenya",
        methods=("Mobile money till",),
        settles="T+1 to your bank",
        available=False,
    ),
    Gateway(
        id="pesapal",
        name="Pesapal",
        region="Pesapal · East Africa",
        methods=("Cards", "Mobile money", "Airtel"),
        settles="To your bank",
        available=False,
    ),
    Gateway(
        id="paystack",
        name="Paystack",
        region="Paystack · Kenya",
        methods=("Cards", "MoMo", "Bank"),
        settles="T+1 to your bank",
        available=False,
    ),
    Gateway(
        id="dpo",
        name="DPO Pay",
        region="DPO · multi-country",
        methods=("Cards", "Mobile money"),
        settles="To your bank",
        available=False,
    ),
    Gateway(
        id="bank",
        name="Bank transfer",
        region="Manual · Kenya",
        methods=("Bank transfer",),
        settles="Direct to your bank",
        available=False,
    ),
]

MANAGED = "wifios"


def lookup(gateway_id: str) -> Gateway | None:
    return next((g for g in GATEWAYS if g.id == gateway_id), None)


def secret_keys(gateway_id: str) -> set[str]:
    gateway = lookup(gateway_id)
    return {f.key for f in gateway.fields if f.secret} if gateway else set()
