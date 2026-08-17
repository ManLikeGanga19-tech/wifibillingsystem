"""Access Control — the Owner edits what each delegated role (admin/care/technician) may do.

Owner only (rbac.manage, which is non-delegable). Saving a role's permissions is immediate: no
token change is needed because capabilities are resolved from the role + this config on every
request, so the very next request an affected employee makes is gated by the new set. Their
console nav catches up on the next /me.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

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

from . import rbac
from .models import OperatorRoleConfig, Role

_PERMS = [
    IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    RequireCapability(rbac.RBAC_MANAGE),   # Owner only — non-delegable
]


def _role_state(operator, role) -> dict:
    return {
        "role": role,
        "label": Role(role).label,
        "capabilities": sorted(rbac.effective_capabilities(operator, role)),
        "default_capabilities": sorted(rbac.default_capabilities(role)),
        "is_custom": OperatorRoleConfig.objects.filter(operator=operator, role=role).exists(),
    }


class AccessControlView(APIView):
    """The whole picture: the assignable-capability catalogue + each role's current set."""

    permission_classes = _PERMS

    @extend_schema(responses=OBJECT_RESPONSE, summary="Roles, their permissions, and the catalogue")
    def get(self, request):
        op = acting_tenant(request)
        return Response({
            "catalog": [
                {"group": group, "capability": cap, "label": label}
                for (group, cap, label) in rbac.CAPABILITY_CATALOG
            ],
            "roles": [_role_state(op, role) for role in rbac.CONFIGURABLE_ROLES],
            # For the UI's own note: these can never be granted to a delegated role.
            "non_delegable": sorted(rbac.NON_DELEGABLE),
        })


class RoleCapabilitiesView(APIView):
    """Set (PUT) or reset-to-default (DELETE) one role's permissions."""

    permission_classes = _PERMS

    def _guard(self, role):
        return role in rbac.CONFIGURABLE_ROLES

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Set a role's permissions")
    def put(self, request, role):
        op = acting_tenant(request)
        if not self._guard(role):
            return Response({"detail": "That role's permissions can't be changed."}, status=400)
        caps = request.data.get("capabilities")
        if not isinstance(caps, list):
            return Response({"detail": "Send a list of capabilities."}, status=400)
        # Keep only real, assignable capabilities — silently drops anything unknown or non-delegable
        # (money.manage / rbac.manage can never be handed out).
        clean = sorted(set(caps) & rbac.ASSIGNABLE_CAPS)
        OperatorRoleConfig.objects.update_or_create(
            operator=op, role=role,
            defaults={"capabilities": clean, "updated_by": request.user},
        )
        audit("rbac_role_updated", operator=op, actor=request.user, role=role, capabilities=clean)
        return Response(_role_state(op, role))

    @extend_schema(responses=OBJECT_RESPONSE, summary="Reset a role to the recommended permissions")
    def delete(self, request, role):
        op = acting_tenant(request)
        if not self._guard(role):
            return Response({"detail": "That role's permissions can't be changed."}, status=400)
        OperatorRoleConfig.objects.filter(operator=op, role=role).delete()
        audit("rbac_role_reset", operator=op, actor=request.user, role=role)
        return Response(_role_state(op, role))
