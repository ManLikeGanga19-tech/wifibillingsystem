"""Settings > Loyalty points: configure the programme, and see it working."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import HOTSPOT_VOUCHERS, SETTINGS_WRITE
from apps.core.permissions import (
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireCapability,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
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

    # Programme CONFIG is a settings screen — Owner/Admin (not the front desk, not the field).
    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
        RequireCapability(SETTINGS_WRITE),
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

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational,
                          RequireCapability(HOTSPOT_VOUCHERS)]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Loyalty programme summary + top holders")
    def get(self, request):
        return Response(summary(acting_tenant(request), search=request.query_params.get("q", "")))


class LoyaltyAccountView(APIView):
    """Look up ONE subscriber's points — balance, what it's worth, which plans it can redeem,
    and recent activity. The screen staff use before redeeming for a walk-in customer."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational,
                          RequireCapability(HOTSPOT_VOUCHERS)]

    @extend_schema(responses=OBJECT_RESPONSE, summary="One subscriber's loyalty account")
    def get(self, request):
        from apps.plans.models import Plan

        from .services import account_for, points_needed_for

        operator = acting_tenant(request)
        cfg = settings_for(operator)
        phone = (request.query_params.get("phone") or "").strip()
        account = account_for(operator, phone)
        balance = account.points_balance if account else 0
        redeemable = []
        if cfg.value_per_point and cfg.value_per_point > 0:
            for plan in Plan.objects.filter(
                operator=operator, is_active=True, plan_type=Plan.PlanType.HOTSPOT
            ).order_by("price"):
                cost = points_needed_for(cfg, plan)
                redeemable.append({
                    "plan_id": plan.id, "plan_name": plan.name, "price": str(plan.price),
                    "points_cost": cost,
                    "affordable": balance >= max(cfg.min_redeem_points, cost),
                })
        entries = []
        if account:
            entries = [
                {
                    "kind": e.kind, "points": e.points, "reason": e.reason,
                    "created_at": e.created_at.isoformat(),
                }
                for e in account.entries.all()[:20]
            ]
        return Response({
            "phone": phone,
            "found": account is not None,
            "points_balance": balance,
            "value_kes": str((cfg.value_per_point or 0) * balance),
            "min_redeem_points": cfg.min_redeem_points,
            "redeemable_plans": redeemable,
            "recent": entries,
        })


class LoyaltyRedeemView(APIView):
    """Redeem a subscriber's points for a reward voucher (staff-assisted). Returns the code to
    hand the customer. Gated exactly like every other money-adjacent write."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
        RequireCapability(HOTSPOT_VOUCHERS),   # the loyalty/voucher desk — Care/Admin/Owner
    ]

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Redeem points for a reward voucher")
    def post(self, request):
        from apps.plans.models import Plan

        from .services import LoyaltyError, redeem_for_voucher

        operator = acting_tenant(request)
        phone = (request.data.get("phone") or "").strip()
        plan = Plan.objects.filter(
            pk=request.data.get("plan_id"), operator=operator,
            plan_type=Plan.PlanType.HOTSPOT,
        ).first()
        if plan is None:
            return Response({"detail": "Choose a valid hotspot plan."}, status=400)
        try:
            redemption = redeem_for_voucher(operator, phone, plan, actor=request.user)
        except LoyaltyError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({
            "detail": "Redeemed.",
            "voucher_code": redemption.voucher.code if redemption.voucher else "",
            "plan": plan.name,
            "points_spent": redemption.points_spent,
            "points_balance": redemption.account.points_balance,
        }, status=201)


class LoyaltyAdjustView(APIView):
    """Manually credit (+) or debit (−) a subscriber's points with a recorded reason."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
        RequireCapability(HOTSPOT_VOUCHERS),   # the loyalty/voucher desk — Care/Admin/Owner
    ]

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Adjust a subscriber's points")
    def post(self, request):
        from .services import LoyaltyError, adjust_points

        operator = acting_tenant(request)
        try:
            points = int(request.data.get("points"))
        except (TypeError, ValueError):
            return Response({"detail": "Enter a whole number of points."}, status=400)
        try:
            account = adjust_points(
                operator, (request.data.get("phone") or "").strip(), points,
                reason=(request.data.get("reason") or "").strip(), actor=request.user,
            )
        except LoyaltyError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response({"detail": "Adjusted.", "points_balance": account.points_balance},
                        status=201)
