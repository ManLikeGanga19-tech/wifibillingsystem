"""What every payment gateway must be able to do.

Three things, and the third is not optional:

  charge()        — take money from a subscriber (STK prompt, card redirect, instructions)
  parse_webhook() — turn whatever the gateway POSTs at us into ONE normalised event
  verify()        — ask the gateway what actually happened

`verify` exists because **callbacks get lost**. That is not a theory: a dropped Daraja
callback is exactly what left paid customers staring at a spinning portal, and the
reconciliation sweep is what fixed it. A gateway without a verify() is a gateway that will
one day take a customer's money and never connect them.

Every gateway also declares its SETTLEMENT — whether the money lands with us or with the
ISP. That single flag is what keeps the wallet honest (see billing.models.Settlement): an
ISP can only ever withdraw what we are actually holding.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


class GatewayError(Exception):
    """The gateway refused, or is misconfigured. The message is shown to a human."""


@dataclass
class ChargeResult:
    """What the customer must do next."""

    #: The gateway's own id for this attempt. We store it and match callbacks on it.
    reference: str
    #: Shown to the customer: "Enter your M-Pesa PIN", or "Pay to paybill 123456".
    instructions: str = ""
    #: Card gateways send the customer away to pay, then bring them back.
    redirect_url: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class PaymentEvent:
    """One normalised "this payment resolved" fact, from a webhook OR a verify query.

    Deliberately gateway-agnostic: the rest of the system must never learn the difference
    between a Daraja callback and a Paystack webhook, or every new gateway would mean
    touching the ledger.
    """

    reference: str
    paid: bool
    receipt: str = ""
    amount: Decimal | None = None
    description: str = ""
    #: True only when we genuinely cannot tell yet (the customer has not entered their PIN).
    pending: bool = False
    raw: dict = field(default_factory=dict)


class PaymentGateway(ABC):
    #: Catalog id. Matches Transaction.gateway.
    id: str = ""
    #: Where the customer's money lands — see billing.models.Settlement. THE flag that
    #: decides whether a sale is withdrawable from us or already in the ISP's pocket.
    settlement: str = "direct"

    def __init__(self, operator, credentials: dict | None = None):
        self.operator = operator
        self.credentials = credentials or {}

    @abstractmethod
    def charge(self, tx) -> ChargeResult: ...

    @abstractmethod
    def parse_webhook(self, payload: dict) -> PaymentEvent | None:
        """None when the payload is not one of ours (or is unreadable). Never raise —
        a webhook handler that 500s makes the gateway retry-storm us."""

    @abstractmethod
    def verify(self, tx) -> PaymentEvent | None:
        """Ask the gateway. None when it still cannot say."""
