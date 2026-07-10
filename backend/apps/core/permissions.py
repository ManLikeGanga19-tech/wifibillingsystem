from rest_framework.permissions import BasePermission

from .tenancy import request_operator


class IsPlatformAdmin(BasePermission):
    """Daniel and platform staff: superusers with no tenant attachment."""

    message = "Platform administrator access required."

    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated and request.user.is_superuser
        )


class TenantIsOperational(BasePermission):
    """Blocks ISP staff whose tenant is pending approval or suspended.
    Platform admins and tenant-less requests pass through (other permissions
    still apply)."""

    message = "Your ISP account is not active yet. Contact the platform administrator."

    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated and request.user.is_superuser:
            return True
        operator = request_operator(request)
        if operator is None:
            return True
        return operator.is_operational
