"""Settings > Operator alerts: router status alerts, outage compensation, sales digest."""

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
from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant

from .services import alert_settings_for


class OperatorAlertSettingsSerializer(serializers.Serializer):
    router_alerts_enabled = serializers.BooleanField(required=False)
    router_alert_phones = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    prefer_whatsapp = serializers.BooleanField(required=False)
    compensate_outages = serializers.BooleanField(required=False)
    sales_digest_enabled = serializers.BooleanField(required=False)

    def validate_router_alert_phones(self, value):
        """Normalise to 2547XXXXXXXX and drop blanks/dupes — the same shape the sender and
        the low-balance alerts use, so a number typed as 0742… still gets the text."""
        out = []
        for raw in value:
            raw = (raw or "").strip()
            if not raw:
                continue
            try:
                num = normalize_msisdn(raw)
            except InvalidPhoneError as exc:
                raise serializers.ValidationError(
                    f"{raw!r} is not a valid Kenyan mobile number."
                ) from exc
            if num not in out:
                out.append(num)
        return out


def _as_dict(row) -> dict:
    return {
        "router_alerts_enabled": row.router_alerts_enabled,
        "router_alert_phones": row.router_alert_phones or [],
        "prefer_whatsapp": row.prefer_whatsapp,
        "compensate_outages": row.compensate_outages,
        "sales_digest_enabled": row.sales_digest_enabled,
    }


class OperatorAlertSettingsView(APIView):
    """Read and update this ISP's operator-alert settings."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    ]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's operator-alert settings")
    def get(self, request):
        return Response(_as_dict(alert_settings_for(acting_tenant(request))))

    @extend_schema(
        request=OperatorAlertSettingsSerializer, responses=OBJECT_RESPONSE,
        summary="Update the operator-alert settings",
    )
    def patch(self, request):
        s = OperatorAlertSettingsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        row = alert_settings_for(operator)
        for field, value in s.validated_data.items():
            setattr(row, field, value)
        row.save()
        audit("operator_alerts_updated", operator=operator, actor=request.user, target=operator,
              **{k: str(v) for k, v in s.validated_data.items()})
        return Response(_as_dict(row))
