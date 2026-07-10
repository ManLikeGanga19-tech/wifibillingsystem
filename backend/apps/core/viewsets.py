"""Tenant-scoped DRF plumbing. Every ISP-facing viewset inherits from these so
tenant isolation is structural, not per-view discipline."""

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser

from .permissions import TenantIsOperational
from .tenancy import request_operator


class TenantScopedMixin:
    """Filters the queryset to the request's operator and stamps it on creation.

    Platform admins (superuser, no operator) see across tenants when no subdomain
    context is present; ISP staff are always confined to their own operator.
    """

    permission_classes = [IsAdminUser, TenantIsOperational]

    def get_operator(self):
        return request_operator(self.request)

    def get_queryset(self):
        qs = super().get_queryset()
        operator = self.get_operator()
        if operator is not None:
            qs = qs.filter(operator=operator)
        return qs

    def perform_create(self, serializer):
        operator = self.get_operator()
        if operator is None:
            raise ValidationError("No tenant context — create requires an operator.")
        extra = {"operator": operator}
        if hasattr(serializer.Meta.model, "created_by"):
            extra["created_by"] = self.request.user
        serializer.save(**extra)


class TenantModelViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    pass


class TenantReadOnlyViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    pass
