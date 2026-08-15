"""The PUBLIC API surface — captive portal, signup, Safaricom callbacks.

Rule: a public endpoint serves an ANONYMOUS person (a WiFi customer, an ISP
signing up). It must therefore **never authenticate anybody** — not even by
accident.

This is not pedantry. Two real bugs came from public views that merely set
`permission_classes = [AllowAny]` while leaving authentication switched on:

1. **CSRF on the captive portal.** Cookies ignore the port, so a staff member
   logged into the console on :4600 had their auth cookie sent to the portal on
   :4700. SessionAuthentication then authenticated them and enforced CSRF — and
   a *customer buying WiFi* got "CSRF Failed: Origin checking failed".

2. **Cross-tenant plan leak.** `PlanViewSet.get_queryset()` branches on
   `is_staff`. An authenticated staff cookie arriving at the portal made it
   resolve the tenant from `acting_tenant()` instead of from the router the
   customer is actually connected to — so the portal could show (and sell) the
   WRONG ISP's plans.

Both vanish if a public endpoint simply refuses to authenticate. Inherit
`PublicAPIView`, or set `authentication_classes = []` explicitly.
"""

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView


def resolve_portal_operator(request, *, allow_default: bool = False):
    """The operator a portal request belongs to: the ISP subdomain (request.tenant) first, then
    the ?router= the customer is physically in front of.

    When neither resolves and `allow_default` is set, fall back to
    PORTAL_DEFAULT_OPERATOR_SLUG — the ISP a bare portal host should wear (staging/single-tenant
    boxes). Unset in production, so an unknown host still resolves to None there. Never returns
    the demo tenant. Returns None if nothing resolves."""
    from apps.provisioning.models import Router

    operator = getattr(request, "tenant", None)
    if operator is None:
        router_id = (request.query_params.get("router") or "").strip()
        if router_id.isdigit():
            router = Router.objects.filter(pk=int(router_id), is_active=True).first()
            operator = router.operator if router else None
    if operator is None and allow_default:
        operator = default_portal_operator()
    return operator


def default_portal_operator():
    """The configured fallback ISP for a portal with no tenant context, or None. See
    PORTAL_DEFAULT_OPERATOR_SLUG. Excludes the demo tenant and inactive operators."""
    slug = getattr(settings, "PORTAL_DEFAULT_OPERATOR_SLUG", "")
    if not slug:
        return None
    from apps.core.models import Operator

    return Operator.objects.filter(slug=slug, is_active=True, is_demo=False).first()


class PublicEndpointMixin:
    """Anonymous-only. No authentication is attempted, so no session is picked up,
    no CSRF is enforced, and staff identity can never bleed into portal logic."""

    authentication_classes = []  # noqa: RUF012 — deliberately empty
    permission_classes = [AllowAny]


class PublicAPIView(PublicEndpointMixin, APIView):
    pass
