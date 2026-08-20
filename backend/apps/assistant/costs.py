"""What the AI assistant actually COSTS the platform — for true-margin tracking.

Free (Haiku) and Pro (Sonnet) turns run on Danamo's key, so their token cost is real platform
expense; BYO turns run on the tenant's own key and cost the platform nothing. We price the
logged token usage per model and convert to KES. The finance report compares this against the
Pro fees charged to show whether the price covers usage.
"""

from decimal import Decimal

from django.conf import settings
from django.db.models import Sum

from .models import AssistantQuestion

_MILLION = Decimal(1_000_000)


def ai_cost_kes(operator=None, *, start=None, end=None) -> Decimal:
    """The platform's real AI token cost (KES) over a window. BYO turns are excluded (the tenant
    pays their own provider). Pass an operator for one ISP, or omit for the platform total."""
    qs = AssistantQuestion.objects.exclude(tier="byo")
    if operator is not None:
        qs = qs.filter(operator=operator)
    if start is not None:
        qs = qs.filter(created_at__gte=start)
    if end is not None:
        qs = qs.filter(created_at__lt=end)

    prices = settings.AI_MODEL_PRICES
    rate = Decimal(str(settings.AI_USD_TO_KES))
    total = Decimal("0")
    # Group by model so each turn is priced with its own rate.
    for row in qs.values("model").annotate(ti=Sum("tokens_in"), to=Sum("tokens_out")):
        price = prices.get(row["model"])
        if not price:
            continue
        in_price, out_price = Decimal(str(price[0])), Decimal(str(price[1]))
        usd = (
            Decimal(row["ti"] or 0) / _MILLION * in_price
            + Decimal(row["to"] or 0) / _MILLION * out_price
        )
        total += usd * rate
    return total.quantize(Decimal("0.01"))
