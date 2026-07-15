"""Which gateway an ISP collects through.

One active at a time. The default is the WIFI.OS paybill, so an ISP sells from day one
without a shortcode of their own — Safaricom takes weeks to approve one, and an ISP who
cannot take money in the meantime is an ISP who signs up with somebody else.
"""

from . import catalog
from .base import ChargeResult, GatewayError, PaymentEvent, PaymentGateway
from .catalog import DIRECT, MANAGED, PLATFORM
from .mpesa import MpesaDaraja, WifiosPaybill

#: catalog id -> adapter. A gateway in the catalog but NOT here is one we show as
#: "coming soon" rather than pretend to support.
ADAPTERS: dict[str, type[PaymentGateway]] = {
    "wifios": WifiosPaybill,
    "mpesa": MpesaDaraja,
}


def credentials_for(operator, gateway_id: str) -> dict:
    from ..models import GatewayCredential

    row = GatewayCredential.objects.filter(operator=operator, gateway=gateway_id).first()
    return row.values if row else {}


def active_gateway_id(operator) -> str:
    return getattr(operator, "payment_gateway", "") or MANAGED


def get_gateway(operator, gateway_id: str = "") -> PaymentGateway:
    """The gateway this ISP's subscribers pay through."""
    gateway_id = gateway_id or active_gateway_id(operator)
    adapter = ADAPTERS.get(gateway_id)
    if adapter is None:
        raise GatewayError(f"{gateway_id} is not available yet.")
    return adapter(operator, credentials_for(operator, gateway_id))


def gateway_for_transaction(tx) -> PaymentGateway:
    """The gateway a transaction was STARTED on — not whatever is active now.

    An ISP who switches gateway mid-flight must not have their in-flight payments verified
    against the wrong account: that would look like a mass failure and strand real money.
    """
    return get_gateway(tx.operator, tx.gateway or MANAGED)


def settlement_of(gateway_id: str) -> str:
    entry = catalog.lookup(gateway_id)
    return entry.settlement if entry else DIRECT


__all__ = [
    "ADAPTERS",
    "DIRECT",
    "MANAGED",
    "PLATFORM",
    "ChargeResult",
    "GatewayError",
    "PaymentEvent",
    "PaymentGateway",
    "active_gateway_id",
    "catalog",
    "credentials_for",
    "gateway_for_transaction",
    "get_gateway",
    "settlement_of",
]
