from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAdminUser

from .models import Plan
from .serializers import PlanSerializer


class PlanViewSet(viewsets.ModelViewSet):
    """Public can list/retrieve active plans (captive portal); staff manage them."""

    serializer_class = PlanSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAdminUser()]

    def get_queryset(self):
        qs = Plan.objects.all()
        if not (self.request.user.is_authenticated and self.request.user.is_staff):
            qs = qs.filter(is_active=True, plan_type=Plan.PlanType.HOTSPOT)
        return qs
