"""Employee management — an Owner/Admin creating and running their ISP's staff logins.

No email-invite flow (this system's model is "email proves an address, it doesn't authorise"):
the owner/admin sets a temp password directly, and the new hire is forced to change it on first
login (must_change_password). Role changes and offboarding call revoke_sessions() so they take
effect immediately, per the design's force-logout decision.

Guardrails: you may only ever assign the DELEGATED roles (admin/care/technician) — never Owner
(ownership transfer is its own thing) and never a platform hat; you cannot edit the Owner through
this screen; and you cannot lock yourself out (deactivate or demote your own account).
"""

from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts.rbac import STAFF_MANAGE
from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.services import audit
from apps.core.viewsets import TenantModelViewSet

from .models import Role, User

MIN_PASSWORD = 8


class StaffSerializer(serializers.ModelSerializer):
    """What the staff list/detail shows — never the password hash."""

    class Meta:
        model = User
        fields = [
            "id", "name", "phone", "email", "role", "is_active",
            "must_change_password", "last_login", "date_joined",
        ]
        read_only_fields = ["must_change_password", "last_login", "date_joined"]


def _validate_role(role):
    if role not in Role.staff_manageable_roles():
        raise ValidationError(
            {"role": "Choose Admin, Customer care, or Technician. Ownership is transferred "
                     "separately, and platform roles cannot be assigned here."}
        )


class StaffCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=MIN_PASSWORD)

    class Meta:
        model = User
        fields = ["id", "name", "phone", "email", "role", "password"]

    def validate_role(self, role):
        _validate_role(role)
        return role

    def validate_phone(self, phone):
        try:
            phone = normalize_msisdn(phone)
        except InvalidPhoneError:
            raise ValidationError("Enter a valid Kenyan phone number.") from None
        if User.objects.filter(phone=phone).exists():
            raise ValidationError("An account with this phone already exists.")
        return phone

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)   # operator arrives via perform_create's save(**extra)
        user.is_staff = True
        user.is_active = True
        user.must_change_password = True   # forced first-login reset
        user.set_password(password)
        user.save()
        return user


class StaffUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["name", "role", "is_active"]

    def validate_role(self, role):
        _validate_role(role)
        return role


class StaffViewSet(TenantModelViewSet):
    """CRUD over an ISP's employees. Owner/Admin only (staff.manage)."""

    read_capability = STAFF_MANAGE
    write_capability = STAFF_MANAGE
    queryset = User.objects.all().order_by("name", "phone")

    def get_serializer_class(self):
        if self.action == "create":
            return StaffCreateSerializer
        if self.action in ("update", "partial_update"):
            return StaffUpdateSerializer
        return StaffSerializer

    def get_queryset(self):
        # super() scopes to this operator; show only the tenant workforce (never platform hats).
        return super().get_queryset().filter(role__in=Role.tenant_roles())

    def _guard_not_owner(self, user):
        # The Owner is not editable through the staff screen — no demoting or disabling the
        # account that holds the money and the ISP.
        if user.role == Role.TENANT_OWNER:
            raise PermissionDenied("The ISP owner cannot be changed from the staff screen.")

    def _guard_not_self(self, user):
        if user.pk == self.request.user.pk:
            raise PermissionDenied("You cannot change your own role or access from here.")

    def perform_create(self, serializer):
        super().perform_create(serializer)   # sets operator
        user = serializer.instance
        audit("staff_created", operator=self.get_operator(), actor=self.request.user,
              target=user, role=user.role)

    def perform_update(self, serializer):
        user = self.get_object()
        self._guard_not_owner(user)
        self._guard_not_self(user)
        before_role, before_active = user.role, user.is_active
        super().perform_update(serializer)
        user.refresh_from_db()
        # A role change or a deactivation must bite NOW — kill their live session.
        if user.role != before_role or user.is_active != before_active:
            user.revoke_sessions()
            audit("staff_updated", operator=self.get_operator(), actor=self.request.user,
                  target=user, role=user.role, is_active=user.is_active)

    def destroy(self, request, *args, **kwargs):
        # Offboarding = deactivate, not delete: their FKs (tickets, audit, created records) are
        # SET_NULL/kept, so history stays intact. The session dies at once.
        user = self.get_object()
        self._guard_not_owner(user)
        self._guard_not_self(user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        user.revoke_sessions()
        audit("staff_offboarded", operator=self.get_operator(), actor=request.user, target=user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        """Set a new temp password for an employee who's locked out or lost theirs. Forces another
        first-login change and logs out any session on the old password."""
        user = self.get_object()
        self._guard_not_owner(user)
        password = request.data.get("password") or ""
        if len(password) < MIN_PASSWORD:
            return Response({"detail": f"Use at least {MIN_PASSWORD} characters."}, status=400)
        user.set_password(password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        user.revoke_sessions()
        audit("staff_password_reset", operator=self.get_operator(), actor=request.user, target=user)
        return Response({"detail": f"{user.name or user.phone}'s password was reset."})
