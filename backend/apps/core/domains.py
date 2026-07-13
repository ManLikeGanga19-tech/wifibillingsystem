"""An ISP's address: acme.wifios.co.ke.

The slug is not a label — it IS the tenant's identity. It resolves the subdomain a
customer's phone lands on, and it is baked into the captive-portal redirect written onto
every one of their routers. Renaming it is therefore a small migration, not an edit, and
this module holds the rules that keep it safe:

  * A slug must be a legal DNS label, because it becomes one.
  * It must not collide with another ISP — including with an ISP's OLD slug that is still
    inside its grace window, or we would hand somebody else's in-flight customers to a
    stranger.
  * The old address keeps working for GRACE_DAYS after a change (see tenancy). Routers
    take time to re-sync and customers keep bookmarks; a rename must not black-hole
    anyone in the meantime.
"""

import re

from django.conf import settings
from django.utils import timezone

from .models import Operator

#: A DNS label: letters/digits, hyphens inside, 3–30 chars. RFC 1035 allows more, but a
#: subdomain a human has to read out over the phone should not.
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")

#: How long an ISP's OLD subdomain keeps resolving after they change it. Long enough for
#: every router to come back online and re-sync, and for a customer's saved link to still
#: work while they learn the new one.
GRACE_DAYS = 30


class DomainError(Exception):
    pass


def normalise(raw: str) -> str:
    return (raw or "").strip().lower().lstrip(".")


def validate(slug: str) -> str:
    slug = normalise(slug)
    if not slug:
        raise DomainError("Choose a subdomain.")
    if len(slug) < 3:
        raise DomainError("Too short — use at least 3 characters.")
    if len(slug) > 30:
        raise DomainError("Too long — use 30 characters or fewer.")
    if not SLUG_RE.match(slug):
        raise DomainError(
            "Use lowercase letters, numbers and hyphens only, starting and ending with a "
            "letter or number."
        )
    if "--" in slug:
        # xn-- is the punycode prefix; a double hyphen invites homograph tricks.
        raise DomainError("Two hyphens in a row are not allowed.")
    if slug in Operator.RESERVED_SLUGS:
        raise DomainError("That name is reserved. Pick another.")
    return slug


def taken_by(slug: str, *, exclude: Operator | None = None) -> Operator | None:
    """Who holds this slug — including an ISP whose OLD slug it is and whose grace window
    has not yet closed. Handing that name to somebody else would route the first ISP's
    still-redirecting customers into a stranger's portal."""
    slug = normalise(slug)
    live = Operator.objects.filter(slug=slug)
    if exclude is not None:
        live = live.exclude(pk=exclude.pk)
    holder = live.first()
    if holder:
        return holder

    cutoff = timezone.now() - timezone.timedelta(days=GRACE_DAYS)
    recent = Operator.objects.filter(previous_slug=slug, slug_changed_at__gte=cutoff)
    if exclude is not None:
        recent = recent.exclude(pk=exclude.pk)
    return recent.first()


def is_available(slug: str, *, exclude: Operator | None = None) -> tuple[bool, str]:
    """(available, why-not). Never leaks WHO holds a name — an unauthenticated-ish
    availability check should not enumerate our customer list."""
    try:
        slug = validate(slug)
    except DomainError as exc:
        return False, str(exc)
    if taken_by(slug, exclude=exclude) is not None:
        return False, "That subdomain is already taken."
    return True, ""


def base_domain() -> str:
    return settings.TENANT_BASE_DOMAIN


def domain_for(operator: Operator) -> str:
    return f"{operator.slug}.{base_domain()}"


def url_for(operator: Operator) -> str:
    """The ISP's real address — what we show them, and what their customers see."""
    return f"https://{domain_for(operator)}"


def portal_url_for(operator: Operator) -> str:
    """Where a ROUTER should send a customer's phone.

    In production this is the ISP's own subdomain. In dev/staging that name does not
    resolve from a phone on a test hotspot, so PORTAL_BASE_URL (an ngrok tunnel, say)
    overrides it — the router still works, and the console still tells the truth about
    what the address will be.
    """
    override = getattr(settings, "PORTAL_BASE_URL", "")
    if override:
        return override.rstrip("/")
    return url_for(operator)


def in_grace(operator: Operator) -> bool:
    if not operator.previous_slug or not operator.slug_changed_at:
        return False
    return operator.slug_changed_at >= timezone.now() - timezone.timedelta(days=GRACE_DAYS)


def grace_ends(operator: Operator):
    if not in_grace(operator):
        return None
    return operator.slug_changed_at + timezone.timedelta(days=GRACE_DAYS)
