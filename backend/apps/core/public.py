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

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView


class PublicEndpointMixin:
    """Anonymous-only. No authentication is attempted, so no session is picked up,
    no CSRF is enforced, and staff identity can never bleed into portal logic."""

    authentication_classes = []  # noqa: RUF012 — deliberately empty
    permission_classes = [AllowAny]


class PublicAPIView(PublicEndpointMixin, APIView):
    pass
