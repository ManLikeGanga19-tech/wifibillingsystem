"""Tenant lifecycle: public ISP signup, platform approval queue, and the ISP's
own business/M-Pesa settings."""

from django.db import transaction as db_transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.core.phone import InvalidPhoneError, normalize_msisdn

from .models import Operator
from .permissions import (
    IsPlatformOwner,
    IsPlatformStaff,
    ReadOnlyForSupport,
    RequireTenant,
)
from .public import PublicAPIView
from .schema import OBJECT_RESPONSE
from .services import audit
from .tenancy import acting_tenant


class SignupSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=40, required=False, allow_blank=True)
    owner_name = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate_phone(self, value):
        try:
            phone = normalize_msisdn(value)
        except InvalidPhoneError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError("An account with this phone already exists.")
        return phone

    def validate(self, attrs):
        slug = slugify(attrs.get("slug") or attrs["business_name"])[:40]
        if not slug or slug in Operator.RESERVED_SLUGS:
            raise serializers.ValidationError({"slug": "This subdomain is not available."})
        if Operator.objects.filter(slug=slug).exists():
            raise serializers.ValidationError({"slug": "This subdomain is already taken."})
        attrs["slug"] = slug
        return attrs


@extend_schema(request=SignupSerializer, responses=OBJECT_RESPONSE,
               summary="Public: an ISP applies for a tenant")
class TenantSignupView(PublicAPIView):
    """Public: an ISP applies for a tenant. Anonymous by design — the applicant has
    no account yet, so authenticating them makes no sense and only invites CSRF."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with db_transaction.atomic():
            operator = Operator.objects.create(
                name=data["business_name"],
                slug=data["slug"],
                status=Operator.Status.PENDING,
                owner_name=data["owner_name"],
                contact_phone=data["phone"],
                contact_email=data["email"],
            )
            User.objects.create_user(
                phone=data["phone"],
                password=data["password"],
                name=data["owner_name"],
                email=data["email"],
                operator=operator,
                is_staff=True,
                role=Role.TENANT_OWNER,
            )
            audit("tenant_signup", operator=operator, target=operator, slug=operator.slug)
        return Response(
            {
                "slug": operator.slug,
                "status": operator.status,
                "detail": (
                    "Application received. You can sign in once the platform "
                    "approves your ISP."
                ),
            },
            status=status.HTTP_201_CREATED,
        )


class PlatformTenantSerializer(serializers.ModelSerializer):
    router_count = serializers.IntegerField(read_only=True)
    staff_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Operator
        fields = [
            "id",
            "name",
            "slug",
            "status",
            "owner_name",
            "contact_phone",
            "contact_email",
            "base_fee",
            "hotspot_commission_pct",
            "pppoe_user_fee",
            "setup_fee",
            "trial_ends_at",
            "approved_at",
            "created_at",
            "router_count",
            "staff_count",
        ]
        read_only_fields = ["slug", "status", "approved_at", "trial_ends_at"]


class PlatformTenantViewSet(viewsets.ModelViewSet):
    """Danamo Tech's tenant management: approval queue, suspension, billing rates.
    Reading is open to platform staff; changing money/status needs the owner."""

    serializer_class = PlatformTenantSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsPlatformStaff()]
        return [IsPlatformOwner()]

    def get_queryset(self):
        return Operator.objects.annotate(
            router_count=Count("routers", filter=Q(routers__is_active=True), distinct=True),
            staff_count=Count("users", filter=Q(users__is_staff=True), distinct=True),
        ).order_by("-created_at")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        from datetime import timedelta

        operator = self.get_object()
        operator.status = Operator.Status.ACTIVE
        operator.approved_at = timezone.now()
        # One month free before the base fee starts (only set on first approval)
        if operator.trial_ends_at is None:
            operator.trial_ends_at = timezone.localdate() + timedelta(days=30)
        operator.save(
            update_fields=["status", "approved_at", "trial_ends_at", "updated_at"]
        )
        audit("tenant_approved", operator=operator, actor=request.user, target=operator)
        return Response({"status": operator.status, "trial_ends_at": operator.trial_ends_at})

    @action(detail=True, methods=["get"])
    def detail_stats(self, request, pk=None):
        """Everything about ONE ISP on a single screen — so support rarely needs
        to walk into their console at all."""
        from django.db.models import Sum

        from apps.billing.models import LedgerEntry, Payout
        from apps.core.analytics_views import EARNING_TYPES
        from apps.core.governance_views import AuditLogSerializer
        from apps.core.models import AuditLog
        from apps.payments.models import Transaction
        from apps.pppoe.models import Client
        from apps.provisioning.models import Router

        op = self.get_object()

        def total(qs, field="amount"):
            return qs.aggregate(v=Sum(field))["v"] or 0

        ledger = LedgerEntry.objects.filter(operator=op)
        routers = Router.objects.filter(operator=op, is_active=True)
        clients = Client.objects.filter(operator=op)

        return Response(
            {
                "tenant": PlatformTenantSerializer(op).data,
                "in_trial": op.in_base_fee_trial(),
                "finance": {
                    "gross_collected": total(
                        ledger.filter(entry_type=LedgerEntry.Type.SALE)
                    ),
                    "platform_revenue": -total(ledger.filter(entry_type__in=EARNING_TYPES)),
                    "wallet_balance": total(ledger),
                    "payouts_paid": total(Payout.objects.filter(
                        operator=op, status=Payout.Status.PAID
                    )),
                    "payouts_pending": total(Payout.objects.filter(
                        operator=op, status=Payout.Status.REQUESTED
                    )),
                },
                "usage": {
                    "pppoe_billable": clients.filter(
                        status__in=Client.BILLABLE_STATUSES
                    ).count(),
                    "pppoe_total": clients.count(),
                    "routers_total": routers.count(),
                    "routers_online": routers.filter(status=Router.Status.ONLINE).count(),
                    "transactions": Transaction.objects.filter(
                        operator=op, status__in=Transaction.SUCCESS_STATUSES
                    ).count(),
                    "staff": op.users.filter(is_staff=True).count(),
                },
                "recent_activity": AuditLogSerializer(
                    AuditLog.objects.filter(operator=op).select_related(
                        "actor", "operator"
                    )[:15],
                    many=True,
                ).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="charge-setup")
    def charge_setup(self, request, pk=None):
        """Bill the one-time setup fee — ONLY for ISPs who opt into assisted
        onboarding (Danamo configures their routers + portal). Self-service ISPs
        are never charged. Idempotent: at most one setup fee per ISP, ever."""
        from apps.billing.services import charge_setup_fee

        operator = self.get_object()
        charged = charge_setup_fee(operator)
        return Response(
            {
                "charged": charged,
                "setup_fee": str(operator.effective_setup_fee),
                "detail": "Setup fee billed." if charged else "Already billed or exempt.",
            }
        )

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        operator = self.get_object()
        operator.status = Operator.Status.SUSPENDED
        operator.save(update_fields=["status", "updated_at"])
        audit("tenant_suspended", operator=operator, actor=request.user, target=operator)
        return Response({"status": operator.status})


class OperatorSettingsSerializer(serializers.ModelSerializer):
    commission_rate = serializers.DecimalField(
        source="hotspot_commission_pct", max_digits=4, decimal_places=2, read_only=True
    )

    class Meta:
        model = Operator
        fields = [
            "name",
            "slug",
            "status",
            "owner_name",
            "contact_phone",
            "contact_email",
            "commission_rate",
            # Saved payout destinations (pre-fill the wallet withdraw form)
            "payout_phone",
            "payout_bank_name",
            "payout_bank_account_number",
            "payout_bank_account_name",
        ]
        read_only_fields = ["slug", "status", "commission_rate"]


@extend_schema(request=OperatorSettingsSerializer, responses=OperatorSettingsSerializer,
               summary="This ISP business details")
class OperatorSettingsView(APIView):
    """The ISP's own business details. Tenant-only: RequireTenant returns 403 for
    a platform user who has not selected an ISP (this used to 404 confusingly)."""

    permission_classes = [IsAdminUser, RequireTenant, ReadOnlyForSupport]

    def get(self, request):
        return Response(OperatorSettingsSerializer(acting_tenant(request)).data)

    def patch(self, request):
        operator = acting_tenant(request)
        serializer = OperatorSettingsSerializer(operator, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit("operator_settings_updated", operator=operator, actor=request.user, target=operator)
        return Response(OperatorSettingsSerializer(operator).data)


@extend_schema(responses=OBJECT_RESPONSE, summary="Custody position across ALL ISPs")
class PlatformReconciliationView(APIView):
    """Custody position across ALL ISPs — the money Danamo holds and owes. The
    aggregator's balance sheet: total collected vs owed to ISPs vs platform
    earnings vs disbursed vs float."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        from django.db.models import Sum

        from apps.billing.models import LedgerEntry, Payout
        from apps.payments.models import C2BPayment, Transaction

        def total(qs, field="amount"):
            return qs.aggregate(v=Sum(field))["v"] or 0

        sales = total(LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.SALE))
        commission = total(LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.COMMISSION))
        fees = total(
            LedgerEntry.objects.filter(
                entry_type__in=[
                    LedgerEntry.Type.BASE_FEE,
                    LedgerEntry.Type.PPPOE_FEE,
                    LedgerEntry.Type.SETUP_FEE,
                ]
            )
        )
        payouts_debit = total(LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.PAYOUT))
        owed_to_isps = total(LedgerEntry.objects.all())
        paid_out = total(Payout.objects.filter(status=Payout.Status.PAID))
        pending_payouts = total(Payout.objects.filter(status=Payout.Status.REQUESTED))

        # Transaction costs the platform bears (estimated; corrected at monthly
        # true-up against the M-Pesa/I&M statement)
        paid_tx = Transaction.objects.filter(status__in=Transaction.SUCCESS_STATUSES)
        collect_cost = total(paid_tx, "platform_cost") + total(
            C2BPayment.objects.all(), "platform_cost"
        )
        payout_cost = total(Payout.objects.filter(status=Payout.Status.PAID), "platform_cost")
        tx_costs = collect_cost + payout_cost
        gross_earnings = -(commission + fees)

        return Response(
            {
                "scope": "all_isps",
                "total_collected": sales,
                # Gross platform fees before transaction costs
                "platform_earnings": gross_earnings,
                # What the M-Pesa/bank rails take (estimated)
                "transaction_costs": tx_costs,
                "collection_costs": collect_cost,
                "payout_costs": payout_cost,
                # True take-home after the rails
                "net_margin": gross_earnings - tx_costs,
                "owed_to_isps": owed_to_isps,
                "total_disbursed": -payouts_debit,
                "paid_out_recorded": paid_out,
                "pending_payouts": pending_payouts,
                "current_float": owed_to_isps,
            }
        )


@extend_schema(responses=OBJECT_RESPONSE, summary="Cross-tenant aggregates")
class PlatformOverviewView(APIView):
    """Cross-tenant aggregates — the ONLY legitimate place for platform-wide
    numbers. Explicitly labelled so they can never be mistaken for one ISP's."""

    permission_classes = [IsPlatformStaff]

    def get(self, request):
        from datetime import timedelta

        from django.db.models import Sum
        from django.utils import timezone

        from apps.billing.models import LedgerEntry
        from apps.payments.models import Transaction
        from apps.provisioning.models import Router, Session

        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        paid_month = Transaction.objects.filter(
            status__in=Transaction.SUCCESS_STATUSES, callback_received_at__gte=month_start
        )
        commission_month = (
            LedgerEntry.objects.filter(
                entry_type=LedgerEntry.Type.COMMISSION, created_at__gte=month_start
            ).aggregate(v=Sum("amount"))["v"]
            or 0
        )
        fees_month = (
            LedgerEntry.objects.filter(
                entry_type__in=[
                    LedgerEntry.Type.BASE_FEE,
                    LedgerEntry.Type.PPPOE_FEE,
                    LedgerEntry.Type.SETUP_FEE,
                ],
                created_at__gte=month_start,
            ).aggregate(v=Sum("amount"))["v"]
            or 0
        )
        return Response(
            {
                "scope": "all_isps",  # never confuse with a single tenant's data
                "tenants_total": Operator.objects.count(),
                "tenants_pending": Operator.objects.filter(
                    status=Operator.Status.PENDING
                ).count(),
                "tenants_active": Operator.objects.filter(
                    status=Operator.Status.ACTIVE
                ).count(),
                "tenants_suspended": Operator.objects.filter(
                    status=Operator.Status.SUSPENDED
                ).count(),
                # Platform earnings = commissions + fees withheld (stored negative)
                "platform_revenue_month": -(commission_month + fees_month),
                "gross_volume_month": paid_month.aggregate(v=Sum("amount"))["v"] or 0,
                "transactions_month": paid_month.count(),
                "routers_online": Router.objects.filter(
                    is_active=True, status=Router.Status.ONLINE
                ).count(),
                "routers_total": Router.objects.filter(is_active=True).count(),
                "active_sessions": Session.objects.filter(
                    status=Session.Status.ACTIVE
                ).count(),
                "new_tenants_30d": Operator.objects.filter(
                    created_at__gte=now - timedelta(days=30)
                ).count(),
            }
        )


