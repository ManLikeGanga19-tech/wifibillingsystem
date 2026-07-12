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


def _requested_tenant(request) -> str | None:
    """Which ISP is this platform user asking to act for?

    Source of truth is the SERVER-SET act-as cookie (written when an
    ImpersonationGrant is opened, cleared when it is closed) — never a value the
    frontend kept in localStorage, which is how it used to drift out of sync with
    the grant. The header and query param remain for scripts and tests.
    """
    from apps.accounts.cookie_auth import ACT_AS_COOKIE

    header = request.headers.get("X-Act-As-Tenant")
    if header:
        return header
    if hasattr(request, "query_params") and request.query_params.get("tenant"):
        return request.query_params["tenant"]
    return request.COOKIES.get(ACT_AS_COOKIE) or None


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
            requested = _requested_tenant(request)
            if not requested:
                return user.operator  # their own ISP, if they run one

            target = Operator.objects.filter(slug=requested, is_active=True).first()
            # Your own ISP is not impersonation — no grant needed.
            if target and user.operator_id and target.pk == user.operator_id:
                return target
            if target and has_live_grant(user, target):
                return target

            # SELF-HEALING (this is the "once and for all" bit): an unknown slug,
            # or a grant that has EXPIRED, must NOT resolve to None. Returning None
            # made RequireTenant 403 every single ISP endpoint, which looked exactly
            # like "the API is down" and could only be cleared by wiping browser
            # storage. Fall back to the user's own ISP instead — still exactly one
            # tenant, still never an implicit "all", but the console keeps working.
            return user.operator

        # Tenant staff are locked to their own operator, whatever the Host says.
        if user.operator_id:
            return user.operator
        return None

    # Unauthenticated (captive portal): tenant comes from the subdomain.
    return getattr(request, "tenant", None)


def is_impersonating(request) -> bool:
    """Is this request being made on somebody else's identity?

    True only when platform staff are acting as a tenant that is NOT their own ISP.
    Daniel running his own WISP through the platform login is not impersonation — that
    is just him, in his own console.

    This exists because impersonation was built for TROUBLESHOOTING, and troubleshooting
    never requires moving money. Without this check a platform account (or anyone who
    steals one) can open a grant, enrol their OWN authenticator, and withdraw an ISP's
    balance — the second factor would be satisfied by the attacker's own phone, which
    makes it worthless. See permissions.NotImpersonating.
    """
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_platform_staff):
        return False
    acting = acting_tenant(request)
    if acting is None:
        return False
    return acting.pk != user.operator_id


# Backwards-compatible alias (older call sites).
request_operator = acting_tenant
