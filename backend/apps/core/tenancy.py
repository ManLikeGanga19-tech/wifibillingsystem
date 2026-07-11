"""Tenant resolution — FAIL CLOSED.

Rule: an ISP-shaped request must resolve to exactly ONE tenant. There is no
"no tenant means show everything" path; that produced a cross-tenant data leak
(a platform admin saw every ISP's transactions merged as if they were one ISP's).
Platform-wide aggregates live only on explicit /platform/ endpoints.

Resolution order for the acting tenant:
  1. Tenant staff  -> always their own operator. A stolen token replayed on
     another tenant's subdomain can never cross over.
  2. Platform staff -> their own home operator (Daniel runs a WISP too), OR a
     foreign tenant they hold a LIVE, AUDITED ImpersonationGrant for, selected
     via the X-Act-As-Tenant header (slug) or ?tenant=<slug>. Setting the header
     alone is NOT enough: without a grant the tenant does not resolve and
     RequireTenant returns 403. Never an implicit "all".
  3. Public/portal  -> the subdomain tenant, or the router's tenant (?router=).
"""

from django.conf import settings
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from .models import ImpersonationGrant, Operator


def has_live_grant(user, operator) -> bool:
    """Is there an unexpired, un-exited impersonation grant letting `user` act as
    `operator`? This is the ONLY way platform staff reach a foreign tenant."""
    return ImpersonationGrant.objects.filter(
        actor=user,
        operator=operator,
        ended_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).exists()


def _slug_from_host(host: str) -> str | None:
    host = host.split(":")[0].lower()
    labels = host.split(".")
    if len(labels) < 2:
        return None
    candidate = labels[0]
    if candidate in Operator.RESERVED_SLUGS or candidate in ("localhost", "127"):
        return None
    return candidate


class TenantMiddleware(MiddlewareMixin):
    """Attaches `request.tenant` (Operator or None) resolved from Host/header."""

    def process_request(self, request):
        slug = _slug_from_host(request.get_host())
        if slug is None and settings.DEBUG:
            slug = request.headers.get("X-Tenant-Slug") or None
        request.tenant = (
            Operator.objects.filter(slug=slug, is_active=True).first() if slug else None
        )


def acting_tenant(request) -> Operator | None:
    """The single tenant this request acts for, or None if it cannot be resolved.

    Callers that serve ISP data MUST treat None as a hard error (see
    TenantScopedMixin / RequireTenant), never as 'unfiltered'.
    """
    user = getattr(request, "user", None)

    if user is not None and user.is_authenticated:
        # Platform staff may act as another tenant, but ONLY through a live,
        # audited ImpersonationGrant — never by simply setting a header.
        if user.is_platform_staff:
            requested = (
                request.headers.get("X-Act-As-Tenant")
                or request.query_params.get("tenant")
                if hasattr(request, "query_params")
                else request.headers.get("X-Act-As-Tenant")
            )
            if not requested:
                return user.operator  # their own ISP, if they run one
            target = Operator.objects.filter(slug=requested, is_active=True).first()
            if target is None:
                return None
            # Your own ISP is not impersonation — no grant needed.
            if user.operator_id and target.pk == user.operator_id:
                return target
            return target if has_live_grant(user, target) else None
        # Tenant staff are locked to their own operator, whatever the Host says.
        if user.operator_id:
            return user.operator
        return None

    # Unauthenticated (captive portal): tenant comes from the subdomain.
    return getattr(request, "tenant", None)


# Backwards-compatible alias (older call sites).
request_operator = acting_tenant
