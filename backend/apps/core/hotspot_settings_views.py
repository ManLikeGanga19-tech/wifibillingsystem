"""Settings > Hotspot: how an ISP runs their captive-hotspot business.

The portal *look* (template, background, language, redirect) lives on Branding — the portal
already reads Branding to theme itself, so that is its natural home. This view owns the
operational lifecycle: when the subscription clock starts, dormant-account pruning, the
login-name prefix, and how long an unsold voucher stays valid. Every value is validated
against the same allow-list the model publishes and the console renders as chips.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HotspotSettings
from .permissions import (
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireTenant,
    TenantIsOperational,
)
from .schema import OBJECT_RESPONSE
from .services import audit
from .tenancy import acting_tenant


class HotspotSettingsSerializer(serializers.Serializer):
    timer_start_mode = serializers.ChoiceField(
        choices=HotspotSettings.TimerStart.choices, required=False
    )
    inactive_prune_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    username_prefix = serializers.RegexField(
        # Letters/digits only, up to 8 — it is prepended to auto-generated logins.
        r"^[A-Za-z0-9]{0,8}$", required=False, allow_blank=True,
        error_messages={"invalid": "Use up to 8 letters or numbers only."},
    )
    voucher_expiry_days = serializers.IntegerField(
        required=False, min_value=0, max_value=3650
    )

    def validate_inactive_prune_days(self, value):
        if value is None:
            return None  # "Never"
        if value not in HotspotSettings.PRUNE_CHOICES:
            raise serializers.ValidationError(
                f"Choose one of {list(HotspotSettings.PRUNE_CHOICES)}, or Never."
            )
        return value


def _as_dict(row: HotspotSettings) -> dict:
    return {
        "timer_start_mode": row.timer_start_mode,
        "inactive_prune_days": row.inactive_prune_days,
        "username_prefix": row.username_prefix,
        "voucher_expiry_days": row.voucher_expiry_days,
        # The console renders chips from these, so the allow-lists live in one place.
        "choices": {
            "timer_start_modes": [
                {"value": v, "label": label} for v, label in HotspotSettings.TimerStart.choices
            ],
            "prune_days": list(HotspotSettings.PRUNE_CHOICES),
        },
    }


class HotspotSettingsView(APIView):
    """Read and update this ISP's captive-hotspot lifecycle settings."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    ]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's hotspot lifecycle settings")
    def get(self, request):
        row, _ = HotspotSettings.objects.get_or_create(operator=acting_tenant(request))
        return Response(_as_dict(row))

    @extend_schema(
        request=HotspotSettingsSerializer, responses=OBJECT_RESPONSE,
        summary="Update hotspot lifecycle settings",
    )
    def patch(self, request):
        s = HotspotSettingsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        row, _ = HotspotSettings.objects.get_or_create(operator=operator)

        for field, value in s.validated_data.items():
            setattr(row, field, value)
        row.save()
        audit("hotspot_settings_updated", operator=operator, actor=request.user,
              target=operator, **{k: str(v) for k, v in s.validated_data.items()})
        return Response(_as_dict(row))
