"""RBAC. Every ISP-facing view composes: IsStaff + TenantIsOperational +
RequireTenant (+ role gate). Read-only roles cannot write anything, anywhere."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from .tenancy import acting_tenant


class IsPlatformStaff(BasePermission):
    """Danamo Tech staff (platform_owner / platform_support)."""

    message = "Platform access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_platform_staff)


class IsPlatformOwner(BasePermission):
    """Platform money decisions (paying out ISPs, changing tenant rates)."""

    message = "Platform owner access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_platform_staff
            and user.can_manage_money
        )


class RequireTenant(BasePermission):
    """FAIL CLOSED: ISP data is never served without exactly one resolved tenant.

    This is the guard that makes the old cross-tenant leak impossible: a platform
    admin with no tenant selected gets 403 here instead of an unfiltered queryset.
    """

    message = (
        "No ISP selected. Platform staff must choose a tenant "
        "(X-Act-As-Tenant header) to view ISP data."
    )

    def has_permission(self, request, view):
        return acting_tenant(request) is not None


class TenantIsOperational(BasePermission):
    """Blocks staff of a tenant that is pending approval or suspended."""

    message = "This ISP account is not active. Contact the platform administrator."

    def has_permission(self, request, view):
        user = request.user
        if user and user.is_authenticated and user.is_platform_staff:
            return True  # platform support must still reach suspended tenants
        operator = acting_tenant(request)
        if operator is None:
            return True  # RequireTenant reports this case
        return operator.is_operational


class ReadOnlyForSupport(BasePermission):
    """Support roles may look, never touch."""

    message = "Your role is read-only."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return not user.is_read_only


class CanManageMoney(BasePermission):
    """Withdrawals: ISP owners only (a manager runs ops but can't move cash out)."""

    message = "Only the ISP owner can withdraw funds."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.can_manage_money
