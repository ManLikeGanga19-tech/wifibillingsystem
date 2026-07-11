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
        """Unauthenticated portal traffic: tenant from subdomain, else ?router=."""
        from apps.provisioning.models import Router

        tenant = getattr(self.request, "tenant", None)
        if tenant is not None:
            return tenant
        router_id = self.request.query_params.get("router", "")
        if router_id.isdigit():
            router = Router.objects.filter(pk=int(router_id), is_active=True).first()
            if router:
                return router.operator
        return None

    def get_queryset(self):
        user = self.request.user
        is_staff = user.is_authenticated and user.is_staff

        if is_staff:
            operator = acting_tenant(self.request)
            if operator is None:
                return Plan.objects.none()  # fail closed
            return Plan.objects.filter(operator=operator)

        operator = self._portal_operator()
        if operator is None:
            return Plan.objects.none()  # fail closed: never expose every ISP's plans
        return Plan.objects.filter(
            operator=operator, is_active=True, plan_type=Plan.PlanType.HOTSPOT
        )

    def perform_create(self, serializer):
        serializer.save(operator=acting_tenant(self.request))
