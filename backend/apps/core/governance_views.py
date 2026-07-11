"""Governance: the platform's oversight surface.

Two things live here:

1. **Audit log** — every state change in the system already writes an AuditLog
   row. This exposes it, filterable, so oversight does not depend on guesswork.
2. **Impersonation** — platform staff entering an ISP's console is a privileged,
   recorded act. It must be justified (reason), time-boxed (expires), explicitly
   ended, and permanently logged. `acting_tenant()` will not resolve a foreign
   tenant without a live grant from here, so this is the only door in.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.cookie_auth import clear_act_as_cookie, set_act_as_cookie

from .models import AuditLog, ImpersonationGrant, Operator
from .permissions import IsPlatformStaff
from .services import audit


def _client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None


# ---- Audit log --------------------------------------------------------------


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.name", read_only=True, default="")
    actor_phone = serializers.CharField(source="actor.phone", read_only=True, default="")
    operator_slug = serializers.CharField(source="operator.slug", read_only=True, default="")
    operator_name = serializers.CharField(source="operator.name", read_only=True, default="")

    class Meta:
        model = AuditLog
        fields = [
            "id", "action", "actor_name", "actor_phone", "operator_slug", "operator_name",
            "target_type", "target_id", "metadata", "ip_address", "created_at",
        ]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only, platform-wide. Append-only by construction — there is no write
    path, so the trail cannot be edited away from the UI."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsPlatformStaff]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor", "operator")
        p = self.request.query_params
        if tenant := p.get("tenant"):
            qs = qs.filter(operator__slug=tenant)
        if action_q := p.get("action"):
            qs = qs.filter(action__icontains=action_q)
        if actor := p.get("actor"):
            qs = qs.filter(actor_id=actor)
        if since := p.get("since"):  # ISO date
            qs = qs.filter(created_at__gte=since)
        return qs.order_by("-created_at")

    @action(detail=False, methods=["get"])
    def actions(self, request):
        """The distinct action names, so the UI can offer a real filter list."""
        names = (
            AuditLog.objects.values_list("action", flat=True).distinct().order_by("action")
        )
        return Response(sorted(set(names)))


# ---- Impersonation ----------------------------------------------------------


class ImpersonationGrantSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.name", read_only=True, default="")
    operator_slug = serializers.CharField(source="operator.slug", read_only=True)
    operator_name = serializers.CharField(source="operator.name", read_only=True)
    is_live = serializers.BooleanField(read_only=True)

    class Meta:
        model = ImpersonationGrant
        fields = [
            "id", "actor_name", "operator_slug", "operator_name", "reason",
            "started_at", "expires_at", "ended_at", "ip_address", "is_live",
        ]


class ImpersonationViewSet(viewsets.ReadOnlyModelViewSet):
    """History of every time platform staff entered an ISP's console."""

    serializer_class = ImpersonationGrantSerializer
    permission_classes = [IsPlatformStaff]

    def get_queryset(self):
        qs = ImpersonationGrant.objects.select_related("actor", "operator")
        p = self.request.query_params
        if tenant := p.get("tenant"):
            qs = qs.filter(operator__slug=tenant)
        if p.get("live") == "true":
            qs = qs.filter(ended_at__isnull=True, expires_at__gt=timezone.now())
        return qs.order_by("-started_at")


class StartImpersonationSerializer(serializers.Serializer):
    tenant = serializers.SlugField()
    reason = serializers.CharField(max_length=200, min_length=5)
    minutes = serializers.IntegerField(
        required=False, min_value=5, max_value=480, default=ImpersonationGrant.DEFAULT_MINUTES
    )


class StartImpersonationView(APIView):
    """Open an audited, time-boxed door into one ISP's console. A reason is
    mandatory — 'why did you look at this ISP's data' must always be answerable."""

    permission_classes = [IsPlatformStaff]

    def post(self, request):
        s = StartImpersonationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        operator = Operator.objects.filter(slug=data["tenant"], is_active=True).first()
        if operator is None:
            return Response({"detail": "Unknown ISP."}, status=status.HTTP_404_NOT_FOUND)
        if request.user.operator_id and operator.pk == request.user.operator_id:
            return Response(
                {"detail": "This is your own ISP — no impersonation needed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        minutes = data.get("minutes") or ImpersonationGrant.DEFAULT_MINUTES
        grant = ImpersonationGrant.objects.create(
            actor=request.user,
            operator=operator,
            reason=data["reason"],
            expires_at=timezone.now() + timedelta(minutes=minutes),
            ip_address=_client_ip(request),
        )
        audit(
            "impersonation_started",
            operator=operator,
            actor=request.user,
            target=grant,
            ip=_client_ip(request),
            reason=grant.reason,
            expires_at=grant.expires_at.isoformat(),
        )
        resp = Response(
            ImpersonationGrantSerializer(grant).data, status=status.HTTP_201_CREATED
        )
        # The acting tenant is SERVER state, set alongside the grant that
        # authorises it — so the two can never drift apart the way a value kept
        # in the browser did.
        return set_act_as_cookie(resp, operator.slug)


class EndImpersonationView(APIView):
    """Close the door. Idempotent — ending an already-ended session is fine."""

    permission_classes = [IsPlatformStaff]

    def post(self, request):
        slug = (request.data.get("tenant") or "").strip()
        qs = ImpersonationGrant.objects.filter(
            actor=request.user, ended_at__isnull=True, expires_at__gt=timezone.now()
        )
        if slug:
            qs = qs.filter(operator__slug=slug)
        ended = 0
        for grant in qs:
            grant.ended_at = timezone.now()
            grant.save(update_fields=["ended_at"])
            audit(
                "impersonation_ended",
                operator=grant.operator,
                actor=request.user,
                target=grant,
                ip=_client_ip(request),
            )
            ended += 1
        # Closing the door also drops the acting-tenant cookie, so the very next
        # request is back in the user's own console. No client cleanup needed.
        return clear_act_as_cookie(Response({"ended": ended}))
