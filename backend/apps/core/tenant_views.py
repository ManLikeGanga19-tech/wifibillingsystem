"""Tenant lifecycle: public ISP signup, platform approval queue, and the ISP's
own business/M-Pesa settings."""

from django.db import transaction as db_transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.phone import InvalidPhoneError, normalize_msisdn

from .models import Operator
from .permissions import IsPlatformAdmin
from .services import audit
from .tenancy import request_operator


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


class TenantSignupView(APIView):
    """Public: an ISP applies for a tenant. Activates only after platform approval."""

    permission_classes = [AllowAny]
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
            "approved_at",
            "created_at",
            "router_count",
            "staff_count",
        ]
        read_only_fields = ["slug", "status", "approved_at"]


class PlatformTenantViewSet(viewsets.ModelViewSet):
    """Daniel's tenant management: approval queue, suspension, billing rates."""

    permission_classes = [IsPlatformAdmin]
    serializer_class = PlatformTenantSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_queryset(self):
        return Operator.objects.annotate(
            router_count=Count("routers", filter=Q(routers__is_active=True), distinct=True),
            staff_count=Count("users", filter=Q(users__is_staff=True), distinct=True),
        ).order_by("-created_at")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        operator = self.get_object()
        operator.status = Operator.Status.ACTIVE
        operator.approved_at = timezone.now()
        operator.save(update_fields=["status", "approved_at", "updated_at"])
        audit("tenant_approved", operator=operator, actor=request.user, target=operator)
        return Response({"status": operator.status})

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        operator = self.get_object()
        operator.status = Operator.Status.SUSPENDED
        operator.save(update_fields=["status", "updated_at"])
        audit("tenant_suspended", operator=operator, actor=request.user, target=operator)
        return Response({"status": operator.status})


class OperatorSettingsSerializer(serializers.ModelSerializer):
    mpesa_passkey = serializers.CharField(write_only=True, required=False, allow_blank=True)
    daraja_consumer_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    daraja_consumer_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    has_mpesa_credentials = serializers.BooleanField(read_only=True)

    class Meta:
        model = Operator
        fields = [
            "name",
            "slug",
            "status",
            "owner_name",
            "contact_phone",
            "contact_email",
            "mpesa_shortcode",
            "mpesa_passkey",
            "daraja_consumer_key",
            "daraja_consumer_secret",
            "has_mpesa_credentials",
        ]
        read_only_fields = ["slug", "status"]


class OperatorSettingsView(APIView):
    """The ISP's own business + M-Pesa settings (secrets write-only, encrypted at rest)."""

    permission_classes = [IsAdminUser]

    def _operator(self, request):
        operator = request_operator(request)
        if operator is None:
            return None
        return operator

    def get(self, request):
        operator = self._operator(request)
        if operator is None:
            return Response({"detail": "No tenant context."}, status=status.HTTP_404_NOT_FOUND)
        return Response(OperatorSettingsSerializer(operator).data)

    def patch(self, request):
        operator = self._operator(request)
        if operator is None:
            return Response({"detail": "No tenant context."}, status=status.HTTP_404_NOT_FOUND)
        serializer = OperatorSettingsSerializer(operator, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        audit("operator_settings_updated", operator=operator, actor=request.user, target=operator)
        return Response(OperatorSettingsSerializer(operator).data)


class ValidateMpesaView(APIView):
    """Live check of the tenant's Daraja credentials: request an OAuth token."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        from apps.payments.daraja import DarajaClient, DarajaError

        operator = request_operator(request)
        if operator is None:
            return Response({"detail": "No tenant context."}, status=status.HTTP_404_NOT_FOUND)
        if not operator.has_mpesa_credentials:
            return Response(
                {"ok": False, "detail": "Save your shortcode and Daraja keys first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            DarajaClient(operator)._token()
        except DarajaError as exc:
            return Response({"ok": False, "detail": str(exc)[:200]})
        return Response({"ok": True, "detail": "Daraja credentials are valid."})
