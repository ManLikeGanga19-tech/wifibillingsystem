from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAdminUser

from apps.core.permissions import TenantIsOperational
from apps.core.tenancy import request_operator

from .models import Plan
from .serializers import PlanSerializer


class PlanViewSet(viewsets.ModelViewSet):
    """Public can list/retrieve active hotspot plans (captive portal); ISP staff
    manage their own plans. Tenant context: staff -> own operator; public -> the
    subdomain tenant or an explicit ?router=<id> (captive portal flow)."""

    serializer_class = PlanSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAdminUser(), TenantIsOperational()]

    def get_queryset(self):
        from apps.provisioning.models import Router

        operator = request_operator(self.request)
        is_staff = self.request.user.is_authenticated and self.request.user.is_staff
        qs = Plan.objects.all()
        if operator is not None:
            qs = qs.filter(operator=operator)
        else:
            router_id = self.request.query_params.get("router", "")
            if router_id.isdigit():
                router = Router.objects.filter(pk=int(router_id), is_active=True).first()
                if router:
                    qs = qs.filter(operator=router.operator)
        if not is_staff:
            qs = qs.filter(is_active=True, plan_type=Plan.PlanType.HOTSPOT)
        return qs

    def perform_create(self, serializer):
        operator = request_operator(self.request)
        if operator is None:
            raise ValidationError("No tenant context.")
        serializer.save(operator=operator)
