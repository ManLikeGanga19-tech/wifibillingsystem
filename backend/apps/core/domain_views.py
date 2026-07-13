"""Settings > Domain: the address an ISP's customers reach them at.

Changing it is the most disruptive setting in the product. The slug resolves the tenant
from the subdomain AND is baked into the captive-portal redirect on every router, so a
careless rename would send every customer to an address their ISP no longer answers.

Three things make it safe:
  * The OLD subdomain keeps resolving for a grace window, so nobody is black-holed while
    routers catch up (core.domains / tenancy).
  * The routers are re-pushed immediately, and the console reports PER ROUTER whether it
    actually landed — an offline router is still on the old address and the ISP is told
    so, rather than shown a green tick.
  * The name cannot be taken by anyone else, including from an ISP whose grace window is
    still open.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.provisioning.models import Router
from apps.provisioning.portal_sync import refresh_portal

from . import domains
from .domains import DomainError
from .permissions import CanManageMoney, RequireTenant, TenantIsOperational
from .schema import OBJECT_RESPONSE
from .services import audit
from .tenancy import acting_tenant


def _router_rows(operator) -> list[dict]:
    rows = []
    for router in Router.objects.filter(operator=operator, is_active=True).order_by("name"):
        rows.append(
            {
                "id": router.id,
                "name": router.name,
                "online": router.status == Router.Status.ONLINE,
                "portal_url": router.portal_url,
                "synced_at": router.portal_synced_at,
                "error": router.portal_sync_error,
                # The only question the ISP actually cares about: is this router sending
                # customers to the address I am on NOW?
                "on_current_domain": bool(
                    router.portal_synced_at
                    and router.portal_url == domains.portal_url_for(operator)
                ),
            }
        )
    return rows


def _state(operator) -> dict:
    return {
        "slug": operator.slug,
        "domain": domains.domain_for(operator),
        "url": domains.url_for(operator),
        "base_domain": domains.base_domain(),
        # Where routers actually send phones. Differs from `url` only in dev/staging,
        # where the real subdomain does not resolve from a test handset.
        "portal_url": domains.portal_url_for(operator),
        "previous_slug": operator.previous_slug,
        "previous_url": (
            f"https://{operator.previous_slug}.{domains.base_domain()}"
            if domains.in_grace(operator)
            else ""
        ),
        "grace_ends": domains.grace_ends(operator),
        "grace_days": domains.GRACE_DAYS,
        "routers": _router_rows(operator),
    }


class DomainView(APIView):
    """The ISP's current address, and the state of every router that points at it."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's domain and router sync state")
    def get(self, request):
        return Response(_state(acting_tenant(request)))


class DomainCheckView(APIView):
    """Is this subdomain free? Answers yes/no and why — never WHO holds it, because an
    availability check must not enumerate our customer list."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Check whether a subdomain is available")
    def get(self, request):
        operator = acting_tenant(request)
        raw = request.query_params.get("slug", "")
        slug = domains.normalise(raw)

        if slug and slug == operator.slug:
            return Response(
                {
                    "slug": slug,
                    "available": True,
                    "current": True,
                    "url": domains.url_for(operator),
                    "reason": "already active",
                }
            )

        available, reason = domains.is_available(slug, exclude=operator)
        return Response(
            {
                "slug": slug,
                "available": available,
                "current": False,
                "url": f"https://{slug}.{domains.base_domain()}" if slug else "",
                "reason": reason,
            }
        )


class ChangeDomainSerializer(serializers.Serializer):
    slug = serializers.CharField(max_length=63)


class ChangeDomainView(APIView):
    """Move the ISP to a new subdomain, and re-push the portal to their routers."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational, CanManageMoney]

    @extend_schema(
        request=ChangeDomainSerializer,
        responses=OBJECT_RESPONSE,
        summary="Change this ISP's subdomain and refresh their routers",
    )
    def post(self, request):
        s = ChangeDomainSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)

        try:
            slug = domains.validate(s.validated_data["slug"])
        except DomainError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if slug == operator.slug:
            return Response(
                {"detail": "That is already your address."}, status=status.HTTP_400_BAD_REQUEST
            )
        if domains.taken_by(slug, exclude=operator) is not None:
            return Response(
                {"detail": "That subdomain is already taken."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_slug = operator.slug
        operator.previous_slug = old_slug
        operator.slug = slug
        operator.slug_changed_at = timezone.now()
        operator.save(update_fields=["slug", "previous_slug", "slug_changed_at", "updated_at"])

        # Routers are still redirecting to the old address. Re-push every one of them; the
        # response tells the ISP how many are being refreshed, and GET /domain/ then shows
        # which actually landed.
        queued = refresh_portal(operator)

        audit(
            "domain_changed",
            operator=operator,
            actor=request.user,
            target=operator,
            old_slug=old_slug,
            new_slug=slug,
            routers_queued=queued,
        )

        state = _state(operator)
        state["routers_queued"] = queued
        return Response(state)
