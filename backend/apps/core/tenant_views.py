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
        """Platform override: activate an ISP by hand.

        Normally an ISP activates ITSELF by verifying its settlement account — no
        human needed, live in minutes. This is the manual path for a flagged signup
        or a special case, and it goes through the SAME activation service so the
        two can never drift (trial start, held-payment release, audit).

        NB: activating without a verified settlement account still will not let money
        move — `can_transact` requires both. That is deliberate.
        """
        from .settlement import activate_operator

        operator = self.get_object()
        released = activate_operator(
            operator, actor=request.user, reason="approved by platform"
        )
        audit("tenant_approved", operator=operator, actor=request.user, target=operator)
        return Response(
            {
                "status": operator.status,
                "trial_ends_at": operator.trial_ends_at,
                "released_payments": released,
                "can_transact": operator.can_transact,
                "settlement_verified": operator.settlement_verified_at is not None,
            }
        )

    @action(detail=True, methods=["get"])
    def detail_stats(self, request, pk=None):
        """Everything about ONE ISP on a single screen — so support rarely needs
        to walk into their console at all."""
        from django.db.models import Sum

        from apps.billing.models import LedgerEntry, Payout, Settlement
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
                    # What we HOLD for them (and could be asked to pay out) — not what they
                    # earned. Sales settled into their own gateway are in gross_collected
                    # above, but we never received that cash.
                    "wallet_balance": total(ledger.filter(settlement=Settlement.PLATFORM)),
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
            # Text this ISP's customers payment receipts + expiry warnings. Drives
            # renewals, but costs money per SMS, so it's theirs to switch off.
            "notify_customers_sms",
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

        from apps.billing.models import LedgerEntry, Payout, Settlement
        from apps.payments.models import C2BPayment, Transaction

        def total(qs, field="amount"):
            return qs.aggregate(v=Sum(field))["v"] or 0

        # This view reconciles CASH — what came through our account, what we still hold,
        # what we have paid out. Sales settled straight into an ISP's own gateway are real
        # revenue but never entered our account, so they are reported SEPARATELY. Folding
        # them into "collected" would claim we received money we never saw, and the
        # reconciliation would never balance against the bank.
        from apps.billing.revenue import platform_earnings

        sale_entries = LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.SALE)
        sales = total(sale_entries.filter(settlement=Settlement.PLATFORM))
        settled_direct = total(sale_entries.filter(settlement=Settlement.DIRECT))
        payouts_debit = total(LedgerEntry.objects.filter(entry_type=LedgerEntry.Type.PAYOUT))
        # What we owe ISPs = what we are HOLDING for them. Platform-settled only: we cannot
        # owe somebody money that went straight into their own account.
        owed_to_isps = total(LedgerEntry.objects.filter(settlement=Settlement.PLATFORM))
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
        # Our fees, across BOTH ledgers (withheld aggregator commission + platform-account
        # accruals). billing.revenue is the single seam so nothing is missed.
        gross_earnings = platform_earnings()

        return Response(
            {
                "scope": "all_isps",
                # Cash that actually passed through our account.
                "total_collected": sales,
                # Sales that went straight to an ISP's own gateway. Real revenue, real fee
                # basis — but we never held a shilling of it, so it is NOT in the numbers
                # above or below.
                "settled_direct_to_isps": settled_direct,
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




class ResetMfaSerializer(serializers.Serializer):
    """Identify the person by id, or just name the ISP and let us find its owner —
    which is what Platform Control actually has in its hand when the phone call comes
    in ("hi, I'm from Acme Networks and I've lost my phone")."""

    user_id = serializers.IntegerField(required=False)
    slug = serializers.SlugField(required=False)
    reason = serializers.CharField(max_length=200)

    def validate(self, attrs):
        if not attrs.get("user_id") and not attrs.get("slug"):
            raise serializers.ValidationError("Give a user_id or an ISP slug.")
        return attrs


@extend_schema(request=ResetMfaSerializer, responses=OBJECT_RESPONSE,
               summary="Clear an ISP owner's lost authenticator (platform owner only)")
class ResetTenantMfaView(APIView):
    """THE LOST PHONE. The last door out of a locked wallet — and, handled carelessly,
    a master key to every ISP's money. So:

      - PLATFORM OWNER only. Support staff cannot switch off somebody's second factor.
      - A reason is mandatory, and it is audited. "Who turned this off, and why" has to
        be answerable months later, in front of an ISP who lost money.
      - The ISP owner is EMAILED. If they did not ask for it, that mail is the alarm.
      - Withdrawals freeze for 24 hours afterwards.
      - It does not let US spend anything: money cannot move on an impersonated session
        at all (core.permissions.CanManageMoney), so nobody here can reset a device and
        then drain the balance.

    Deliberately a HUMAN step, gated behind an identity check we do off-system. An
    automated "email me a reset link" would just be the email factor again, which is
    the exact weakness TOTP was brought in to fix.
    """

    permission_classes = [IsPlatformOwner]

    def post(self, request):
        from apps.accounts import mfa

        s = ResetMfaSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        if s.validated_data.get("user_id"):
            target = User.objects.filter(pk=s.validated_data["user_id"]).first()
        else:
            target = (
                User.objects.filter(
                    operator__slug=s.validated_data["slug"], role=Role.TENANT_OWNER
                )
                .order_by("id")
                .first()
            )
        if target is None:
            return Response({"detail": "No such user."}, status=status.HTTP_404_NOT_FOUND)

        try:
            mfa.reset_device(target, by=request.user, reason=s.validated_data["reason"])
        except mfa.MfaError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        audit(
            "mfa_reset",
            operator=target.operator,
            actor=request.user,
            target=target,
            reason=s.validated_data["reason"],
            target_email=target.email,
        )
        return Response(
            {
                "detail": (
                    f"Authenticator cleared for {target.email or target.phone}. They have "
                    "been emailed, and their withdrawals are frozen for 24 hours."
                ),
                "freeze_hours": mfa.PAYOUT_FREEZE_HOURS,
            }
        )
