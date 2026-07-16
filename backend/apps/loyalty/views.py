"""Settings > Loyalty points: configure the programme, and see it working."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import (
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant

from .models import LoyaltySettings
from .services import settings_for, summary


class LoyaltySettingsSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(required=False)
    spend_per_point = serializers.IntegerField(required=False, min_value=1, max_value=1_000_000)
    points_per_threshold = serializers.IntegerField(required=False, min_value=1, max_value=10_000)
    min_redeem_points = serializers.IntegerField(required=False, min_value=0, max_value=1_000_000)
    value_per_point = serializers.DecimalField(
        required=False, max_digits=8, decimal_places=2, min_value=0
    )


def _as_dict(row: LoyaltySettings) -> dict:
    return {
        "is_enabled": row.is_enabled,
        "spend_per_point": row.spend_per_point,
        "points_per_threshold": row.points_per_threshold,
        "min_redeem_points": row.min_redeem_points,
        "value_per_point": str(row.value_per_point),
    }


class LoyaltySettingsView(APIView):
    """Read and update this ISP's loyalty programme."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    ]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's loyalty programme settings")
    def get(self, request):
        return Response(_as_dict(settings_for(acting_tenant(request))))

    @extend_schema(
        request=LoyaltySettingsSerializer, responses=OBJECT_RESPONSE,
        summary="Update the loyalty programme",
    )
    def patch(self, request):
        s = LoyaltySettingsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        row = settings_for(operator)
        for field, value in s.validated_data.items():
            setattr(row, field, value)
        row.save()
        audit("loyalty_settings_updated", operator=operator, actor=request.user, target=operator,
              **{k: str(v) for k, v in s.validated_data.items()})
        return Response(_as_dict(row))


class LoyaltySummaryView(APIView):
    """Programme health: how many subscribers are enrolled, points outstanding, top holders."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Loyalty programme summary + top holders")
    def get(self, request):
        return Response(summary(acting_tenant(request), search=request.query_params.get("q", "")))
