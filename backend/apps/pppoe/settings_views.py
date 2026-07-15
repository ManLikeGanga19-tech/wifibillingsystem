"""Settings > PPPoE: how an ISP runs their fixed-line business.

Every value is validated against the SAME allow-lists the model publishes (and the console
renders as chips), so the API can never store a threshold the behaviour does not understand.
Only choices that map to real behaviour are accepted — a settings page that silently drops
a value is worse than one that says no.
"""

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

from .models import PppoeSettings


class _ChoiceList(serializers.ListField):
    """A list whose every element must come from a fixed set — deduped and sorted so the
    stored value is canonical."""

    def __init__(self, *, allowed, **kwargs):
        self._allowed = set(allowed)
        super().__init__(child=serializers.IntegerField(), **kwargs)

    def to_internal_value(self, data):
        values = super().to_internal_value(data)
        bad = [v for v in values if v not in self._allowed]
        if bad:
            raise serializers.ValidationError(
                f"Unsupported value(s): {bad}. Allowed: {sorted(self._allowed)}."
            )
        return sorted(set(values))


class PppoeSettingsSerializer(serializers.Serializer):
    inactive_prune_days = serializers.IntegerField(required=False, allow_null=True)
    pre_expiry_reminder_hours = _ChoiceList(
        allowed=PppoeSettings.REMINDER_HOUR_CHOICES, required=False
    )
    fup_alert_percents = _ChoiceList(
        allowed=PppoeSettings.FUP_PERCENT_CHOICES, required=False
    )
    auto_generate_invoices = serializers.BooleanField(required=False)
    invoice_prefix = serializers.RegexField(
        # Letters/digits only, 1–8 chars — it becomes part of an invoice number.
        r"^[A-Za-z0-9]{1,8}$", required=False,
        error_messages={"invalid": "Use 1–8 letters or numbers only."},
    )

    def validate_inactive_prune_days(self, value):
        if value is None:
            return None  # "Never"
        if value not in PppoeSettings.PRUNE_CHOICES:
            raise serializers.ValidationError(
                f"Choose one of {list(PppoeSettings.PRUNE_CHOICES)}, or Never."
            )
        return value


def _as_dict(row: PppoeSettings) -> dict:
    return {
        "inactive_prune_days": row.inactive_prune_days,
        "pre_expiry_reminder_hours": row.pre_expiry_reminder_hours,
        "fup_alert_percents": row.fup_alert_percents,
        "auto_generate_invoices": row.auto_generate_invoices,
        "invoice_prefix": row.invoice_prefix,
        # The console renders chips from these, so the allow-lists live in one place.
        "choices": {
            "prune_days": list(PppoeSettings.PRUNE_CHOICES),
            "reminder_hours": list(PppoeSettings.REMINDER_HOUR_CHOICES),
            "fup_percents": list(PppoeSettings.FUP_PERCENT_CHOICES),
        },
        # Honesty: FUP thresholds are stored but inert until per-client usage metering
        # exists. The UI reads this to say so rather than imply an alert will fire.
        "fup_metering_ready": False,
    }


class PppoeSettingsView(APIView):
    """Read and update this ISP's fixed-line lifecycle settings."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    ]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's PPPoE lifecycle settings")
    def get(self, request):
        row, _ = PppoeSettings.objects.get_or_create(operator=acting_tenant(request))
        return Response(_as_dict(row))

    @extend_schema(
        request=PppoeSettingsSerializer, responses=OBJECT_RESPONSE,
        summary="Update PPPoE lifecycle settings",
    )
    def patch(self, request):
        s = PppoeSettingsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        row, _ = PppoeSettings.objects.get_or_create(operator=operator)

        for field, value in s.validated_data.items():
            setattr(row, field, value)
        row.save()
        audit("pppoe_settings_updated", operator=operator, actor=request.user,
              target=operator, **{k: str(v) for k, v in s.validated_data.items()})
        return Response(_as_dict(row))
