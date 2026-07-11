from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAdminUser

from apps.core.permissions import ReadOnlyForSupport, RequireTenant, TenantIsOperational
from apps.core.tenancy import acting_tenant

from .models import Plan
from .serializers import PlanSerializer


class PlanViewSet(viewsets.ModelViewSet):
    """Public list/retrieve for the captive portal (tenant from the subdomain or
    ?router=); staff manage their own tenant's plans."""

    serializer_class = PlanSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAdminUser(), RequireTenant(), TenantIsOperational(), ReadOnlyForSupport()]

    def _portal_operator(self):
        """Unauthenticated portal traffic: tenant from subdomain, else ?router=.

        Returns None for an ISP that cannot transact — a hotspot whose owner is not
        verified is NOT LIVE, so it must not offer anything for sale. Showing plans
        we would then refuse to charge for is worse than showing none.
        """
        from apps.provisioning.models import Router

        tenant = getattr(self.request, "tenant", None)
        if tenant is None:
            router_id = self.request.query_params.get("router", "")
            if router_id.isdigit():
                router = Router.objects.filter(pk=int(router_id), is_active=True).first()
                if router:
                    tenant = router.operator
        if tenant is None or not tenant.can_transact:
            return None
        return tenant

    def get_queryset(self):
        # PORTAL TRAFFIC WINS. `?router=` means a WiFi customer is standing in front
        # of that router — the plans they may buy are that ROUTER'S owner's plans,
        # full stop. Never acting_tenant().
        #
        # This ordering is load-bearing. Cookies ignore the port, so a staff member
        # logged into the console had their cookie sent to the portal too; the old
        # `if is_staff:` branch then resolved the tenant from THEIR acting tenant and
        # the portal would show — and sell — the wrong ISP's plans to that customer.
        if self.request.query_params.get("router", "").isdigit():
            operator = self._portal_operator()
            return (
                Plan.objects.filter(
                    operator=operator, is_active=True, plan_type=Plan.PlanType.HOTSPOT
                )
                if operator
                else Plan.objects.none()  # fail closed
            )

        user = self.request.user
        if user.is_authenticated and user.is_staff:
            operator = acting_tenant(self.request)
            if operator is None:
                return Plan.objects.none()  # fail closed
            return Plan.objects.filter(operator=operator)

        # Anonymous, no router: the subdomain is the only tenant signal.
        operator = self._portal_operator()
        if operator is None:
            return Plan.objects.none()  # fail closed: never expose every ISP's plans
        return Plan.objects.filter(
            operator=operator, is_active=True, plan_type=Plan.PlanType.HOTSPOT
        )

    def perform_create(self, serializer):
        serializer.save(operator=acting_tenant(self.request))
