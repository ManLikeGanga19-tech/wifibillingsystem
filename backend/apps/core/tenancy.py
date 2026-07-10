"""Tenant resolution.

Production: the tenant is the subdomain — `<slug>.wifios.co.ke`.
Dev (DEBUG): an `X-Tenant-Slug` header may substitute, and `<slug>.localhost` works too.

Security rule: an authenticated staff user's OWN operator always wins over the Host
header — a stolen token replayed on another tenant's subdomain must never cross data.
Platform admins (is_superuser, operator=None) float across tenants.
"""

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

from .models import Operator


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


def request_operator(request) -> Operator | None:
    """The operator this request acts for.

    Priority: authenticated staff user's own operator > subdomain tenant > None.
    """
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.operator_id:
        return user.operator
    return getattr(request, "tenant", None)
