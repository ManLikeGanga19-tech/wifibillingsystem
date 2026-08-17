"""Tenant-scoped DRF plumbing.

Isolation is STRUCTURAL: `get_queryset()` always filters by exactly one operator,
and `RequireTenant` guarantees one exists. There is no code path that returns
unfiltered ISP data — the previous "operator is None -> don't filter" behaviour
leaked every tenant's data to platform admins.
"""

from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAdminUser

from .permissions import (
    HasViewsetCapability,
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireTenant,
    TenantIsOperational,
)
from .tenancy import acting_tenant


class TenantScopedMixin:
    #: RBAC Layer A. Subclasses declare the capability their reads/writes need (a string or an
    #: any-of iterable); None on either leaves that method ungated. See HasViewsetCapability.
    read_capability = None
    write_capability = None

    permission_classes = [
        IsAdminUser,
        RequireTenant,
        TenantIsOperational,
        ReadOnlyForSupport,
        # Delegated-role gate: enforces read_capability / write_capability declared below.
        HasViewsetCapability,
        # Past-due lockout is read-only + pay. The pay/top-up views are plain APIViews that
        # do NOT compose this mixin, so they stay open even when everything else is locked.
        NotBillingLocked,
    ]

    def get_operator(self):
        operator = acting_tenant(self.request)
        if operator is None:
            # Defence in depth: RequireTenant should already have rejected this.
            raise PermissionDenied(RequireTenant.message)
        return operator

    def get_queryset(self):
        return super().get_queryset().filter(operator=self.get_operator())

    def perform_create(self, serializer):
        extra = {"operator": self.get_operator()}
        if hasattr(serializer.Meta.model, "created_by"):
            extra["created_by"] = self.request.user
        serializer.save(**extra)


class TenantModelViewSet(TenantScopedMixin, viewsets.ModelViewSet):
    pass


class TenantReadOnlyViewSet(TenantScopedMixin, viewsets.ReadOnlyModelViewSet):
    pass
