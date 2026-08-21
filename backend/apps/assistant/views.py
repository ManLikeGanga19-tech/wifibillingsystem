"""Settings > AI Assistant: configure the provider + optional BYO key, and the chat endpoint."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.rbac import MONEY_MANAGE
from apps.core.permissions import (
    IsPlatformOwner,
    IsPlatformStaff,
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireCapability,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_REQUEST, OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant

from .models import (
    AssistantQuestion,
    Conversation,
    ConversationMessage,
    PlatformAISettings,
    Provider,
)
from .providers import (
    AssistantError,
    AssistantQuotaExceeded,
    AssistantRateLimited,
    AssistantUnavailable,
    chat,
    platform_default_provider,
    platform_key_configured,
    settings_for,
    usage_status,
)

# A sentinel distinct from "" (which explicitly CLEARS the key) and from absent (leave unchanged).
_UNSET = object()


def _key_preview(key: str) -> str:
    """A recognisable hint — provider prefix + last 4 — never the whole secret."""
    key = key or ""
    if len(key) < 12:
        return "••••" if key else ""
    return f"{key[:7]}…{key[-4:]}"


def _as_dict(row) -> dict:
    return {
        "provider": row.provider,
        "has_own_key": bool((row.api_key or "").strip()),
        "key_preview": _key_preview((row.api_key or "").strip()),
        "platform_default_available": platform_key_configured(),
        "platform_default_provider": platform_default_provider(),
    }


class AISettingsSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=Provider.choices, required=False)
    # Optional. Absent -> unchanged. "" -> clear (use platform default). A value -> set it.
    api_key = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs):
        key = attrs.get("api_key", _UNSET)
        if key in (_UNSET, ""):
            return attrs  # nothing to format-check
        provider = attrs.get("provider") or self.context["provider"]
        if provider == Provider.CLAUDE and not key.startswith("sk-ant-"):
            raise serializers.ValidationError(
                {"api_key": "Anthropic (Claude) keys start with sk-ant-."}
            )
        if provider == Provider.OPENAI and (not key.startswith("sk-") or key.startswith("sk-ant-")):
            raise serializers.ValidationError({"api_key": "OpenAI keys start with sk-."})
        return attrs


class AISettingsView(APIView):
    """Read and update this ISP's AI-assistant settings."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    ]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's AI-assistant settings")
    def get(self, request):
        return Response(_as_dict(settings_for(acting_tenant(request))))

    @extend_schema(
        request=AISettingsSerializer, responses=OBJECT_RESPONSE,
        summary="Update the AI-assistant provider and/or key",
    )
    def patch(self, request):
        operator = acting_tenant(request)
        row = settings_for(operator)
        s = AISettingsSerializer(data=request.data, context={"provider": row.provider})
        s.is_valid(raise_exception=True)
        data = s.validated_data

        fields = []
        if "provider" in data:
            row.provider = data["provider"]
            fields.append("provider")
        key_changed = False
        if "api_key" in data:
            row.api_key = data["api_key"].strip()
            fields.append("api_key")
            key_changed = True
        if fields:
            row.save()
        # Audit the decision — provider and WHETHER a key is present, never the key itself.
        audit("ai_settings_updated", operator=operator, actor=request.user, target=operator,
              provider=row.provider, own_key=bool(row.api_key), key_changed=key_changed)
        return Response(_as_dict(row))


def _chat_error_response(exc, operator):
    """Map an assistant exception to the right HTTP response — shared by the one-shot chat endpoint
    and the conversation message action so they behave identically."""
    if isinstance(exc, ValueError):
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, AssistantUnavailable):
        return Response({"detail": str(exc), "code": "not_configured"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if isinstance(exc, AssistantQuotaExceeded):
        return Response({"detail": str(exc), "code": "quota_exceeded",
                         "usage": usage_status(operator)},
                        status=status.HTTP_402_PAYMENT_REQUIRED)
    if isinstance(exc, AssistantRateLimited):
        return Response({"detail": str(exc), "code": "rate_limited"},
                        status=status.HTTP_429_TOO_MANY_REQUESTS)
    if isinstance(exc, AssistantError):
        return Response({"detail": str(exc), "code": "provider_error"},
                        status=status.HTTP_502_BAD_GATEWAY)
    raise exc


def _log_question(operator, question_text, result) -> AssistantQuestion:
    """Record the docs-gaps analytics row for one turn — tenant-scoped, topic-tagged."""
    return AssistantQuestion.objects.create(
        operator=operator,
        question=str(question_text)[:2000],
        grounded=result["grounded"],
        top_score=result["top_score"],
        topic=result.get("topic", ""),
        tier=result.get("tier", ""),
        model=result.get("model", ""),
        tokens_in=result.get("tokens_in", 0),
        tokens_out=result.get("tokens_out", 0),
    )


class ChatSerializer(serializers.Serializer):
    messages = serializers.ListField(child=serializers.DictField(), allow_empty=False)


class AIChatView(APIView):
    """One stateless turn of the dashboard assistant (the client sends the full history)."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(
        request=ChatSerializer, responses=OBJECT_RESPONSE, summary="Ask the AI assistant",
    )
    def post(self, request):
        s = ChatSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        messages = s.validated_data["messages"]
        try:
            result = chat(operator, messages)
        except (ValueError, AssistantUnavailable, AssistantQuotaExceeded,
                AssistantRateLimited, AssistantError) as exc:
            return _chat_error_response(exc, operator)

        last_user = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        question_row = _log_question(operator, last_user, result)
        return Response({
            "reply": result["reply"],
            "sources": result["sources"],
            "question_id": question_row.id,  # so the UI can attach a 👍/👎 rating later
            "usage": usage_status(operator),
        })


class AIUsageView(APIView):
    """This ISP's assistant tier and this month's usage — drives the widget meter and upgrade
    prompt. No key needed, so the console can always show where the ISP stands."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(responses=OBJECT_RESPONSE, summary="AI assistant tier & monthly usage")
    def get(self, request):
        return Response(usage_status(acting_tenant(request)))


class AIProToggleView(APIView):
    """Turn the paid Pro tier on or off. Owner-only (money.manage) because it commits the ISP to
    a recurring platform fee; audited on every flip. Self-serve + postpaid: flipping it on starts
    the monthly fee accruing to their platform account like any other fee."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational,
                          RequireCapability(MONEY_MANAGE)]

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Enable/disable Pro AI (owner-only, adds a monthly fee)")
    def post(self, request):
        from django.conf import settings as dj_settings

        enable = bool(request.data.get("enabled"))
        # Self-serve Pro is feature-flagged off for now — turning it ON is blocked; turning it OFF
        # is always allowed so no one is ever stuck on a paid tier.
        if enable and not getattr(dj_settings, "AI_PRO_SELF_SERVE", False):
            return Response(
                {"detail": "Pro AI isn't available for self-serve yet — it's coming soon.",
                 "code": "pro_unavailable"},
                status=status.HTTP_403_FORBIDDEN,
            )
        operator = acting_tenant(request)
        row = settings_for(operator)
        if row.pro_ai != enable:
            row.pro_ai = enable
            row.save(update_fields=["pro_ai"])
            audit("ai_pro_enabled" if enable else "ai_pro_disabled",
                  operator=operator, actor=request.user, target=operator,
                  monthly_fee=str(dj_settings.AI_PRO_MONTHLY_FEE))
        return Response({**usage_status(operator),
                         "monthly_fee": str(dj_settings.AI_PRO_MONTHLY_FEE)})


class PlatformAISettingsView(APIView):
    """Platform staff manage the CROSS-TENANT key — the shared key every free/Pro tenant rides
    when they haven't brought their own. Owner-level: it's a secret that spends Danamo's money."""

    permission_classes = [IsPlatformOwner]

    def _as_dict(self, row) -> dict:
        return {
            "provider": row.provider,
            "has_key": bool((row.api_key or "").strip()),
            "key_preview": _key_preview((row.api_key or "").strip()),
            "enabled": row.enabled,
            "rate_limit_per_min": row.rate_limit_per_min,
            # So the UI can say "an environment fallback exists" when no DB key is set.
            "env_fallback_available": platform_key_configured(),
        }

    @extend_schema(responses=OBJECT_RESPONSE, summary="Platform (cross-tenant) AI key settings")
    def get(self, request):
        return Response(self._as_dict(PlatformAISettings.load()))

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Update the platform (cross-tenant) AI key")
    def patch(self, request):
        row = PlatformAISettings.load()
        data = request.data
        if "provider" in data and data["provider"] in dict(Provider.choices):
            row.provider = data["provider"]
        if "enabled" in data:
            row.enabled = bool(data["enabled"])
        if "rate_limit_per_min" in data:
            try:
                row.rate_limit_per_min = max(0, int(data["rate_limit_per_min"]))
            except (TypeError, ValueError):
                return Response({"detail": "rate_limit_per_min must be a number."}, status=400)
        # A value sets the key; "" clears it (falling back to the env key); absent leaves it.
        key_changed = False
        if "api_key" in data:
            row.api_key = str(data["api_key"]).strip()
            key_changed = True
        row.save()
        # Audit provider/enabled/rate and WHETHER a key is present — never the key itself.
        audit("platform_ai_settings_updated", actor=request.user, target=None,
              provider=row.provider, enabled=row.enabled,
              rate_limit_per_min=row.rate_limit_per_min,
              has_key=bool(row.api_key), key_changed=key_changed)
        return Response(self._as_dict(row))


class PlatformDocsGapsView(APIView):
    """The docs-gaps report: what tenants ask the assistant, and where it had no grounded answer —
    aggregated ACROSS tenants and fully anonymised (topic = a doc-page slug + counts; never the
    question text or which ISP asked). This is the signal for what docs to write or improve next."""

    permission_classes = [IsPlatformStaff]

    @extend_schema(
        parameters=[OpenApiParameter("days", int, description="Look-back window (default 30)")],
        responses=OBJECT_RESPONSE,
        summary="AI assistant docs-gaps report (cross-tenant, anonymised)",
    )
    def get(self, request):
        from datetime import timedelta

        from django.db.models import Count, Q, Sum
        from django.utils import timezone

        try:
            days = max(1, min(int(request.query_params.get("days", 30)), 365))
        except (TypeError, ValueError):
            days = 30
        qs = AssistantQuestion.objects.filter(created_at__gte=timezone.now() - timedelta(days=days))

        total = qs.count()
        grounded = qs.filter(grounded=True).count()
        top_topics = list(
            qs.exclude(topic="").values("topic")
            .annotate(count=Count("id"), answered=Count("id", filter=Q(grounded=True)))
            .order_by("-count")[:15]
        )
        # The gaps: unanswered questions, by the doc they were NEAREST to — i.e. what to write.
        gaps = list(
            qs.filter(grounded=False).exclude(topic="").values("topic")
            .annotate(count=Count("id")).order_by("-count")[:15]
        )
        thumbs_down = list(
            qs.filter(rating=-1).exclude(topic="").values("topic")
            .annotate(count=Count("id")).order_by("-count")[:10]
        )

        # True margin: what the assistant COST us (real token spend on the platform key) versus
        # the Pro fees we CHARGED, over the same window. BYO turns cost us nothing.
        from decimal import Decimal

        from apps.billing.models import PlatformLedgerEntry

        from .costs import ai_cost_kes

        since = timezone.now() - timedelta(days=days)
        cost = ai_cost_kes(start=since)
        pro_revenue = -(
            PlatformLedgerEntry.objects.filter(
                reason=PlatformLedgerEntry.Reason.AI_PRO, created_at__gte=since,
            ).aggregate(v=Sum("amount"))["v"] or Decimal("0")
        )
        return Response({
            "days": days,
            "total_questions": total,
            "grounded": grounded,
            "unanswered": total - grounded,
            "grounded_rate": round(grounded / total, 3) if total else None,
            "top_topics": top_topics,
            "gaps": gaps,
            "thumbs_down": thumbs_down,
            # Cross-tenant true-margin, KES.
            "ai_cost_kes": str(cost),
            "pro_revenue_kes": str(pro_revenue),
            "ai_margin_kes": str(pro_revenue - cost),
        })


class AIRateView(APIView):
    """Record a 👍/👎 on one earlier answer — feedback that tunes the docs-gaps report. Tenant-
    scoped: you can only rate your own ISP's questions."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE, summary="Rate an answer")
    def post(self, request, pk):
        raw = request.data.get("rating")
        try:
            rating = int(raw)
        except (TypeError, ValueError):
            return Response({"detail": "rating must be 1, -1 or 0."}, status=400)
        if rating not in (1, -1, 0):
            return Response({"detail": "rating must be 1, -1 or 0."}, status=400)
        row = AssistantQuestion.objects.filter(
            operator=acting_tenant(request), id=pk
        ).first()
        if not row:
            return Response({"detail": "Not found."}, status=404)
        row.rating = rating or None  # 0 clears it
        row.save(update_fields=["rating"])
        return Response({"rating": row.rating})


# ---- Multi-conversation chat: saved, named threads (per tenant + per staff member) -----------


class ConvMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversationMessage
        fields = ["id", "role", "content", "sources", "question_id", "created_at"]


class ConversationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "updated_at"]


class ConversationDetailSerializer(serializers.ModelSerializer):
    messages = ConvMessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "updated_at", "messages"]


class ConversationViewSet(viewsets.ModelViewSet):
    """Saved assistant chats. Scoped to the tenant AND the signed-in staff member, so each
    person's threads are private to them. The transcript lives on the server (no browser storage),
    so it survives reloads and sign-ins."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]
    # For schema/router introspection only; get_queryset() below is the real, scoped source.
    queryset = Conversation.objects.all()
    search_fields = ["title"]
    ordering_fields = ["updated_at", "created_at"]

    def get_queryset(self):
        return Conversation.objects.filter(
            operator=acting_tenant(self.request), user=self.request.user
        )

    def get_serializer_class(self):
        return ConversationListSerializer if self.action == "list" else ConversationDetailSerializer

    def perform_create(self, serializer):
        serializer.save(operator=acting_tenant(self.request), user=self.request.user)

    @extend_schema(request=OBJECT_REQUEST, responses=OBJECT_RESPONSE,
                   summary="Send a message in this conversation")
    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        convo = self.get_object()
        content = str(request.data.get("content", "")).strip()
        if not content:
            return Response({"detail": "Message is empty."}, status=400)

        operator = acting_tenant(request)
        history = [{"role": m.role, "content": m.content} for m in convo.messages.all()]
        history.append({"role": "user", "content": content})
        try:
            result = chat(operator, history)
        except (ValueError, AssistantUnavailable, AssistantQuotaExceeded,
                AssistantRateLimited, AssistantError) as exc:
            return _chat_error_response(exc, operator)

        ConversationMessage.objects.create(conversation=convo, role="user", content=content)
        qrow = _log_question(operator, content, result)
        assistant_msg = ConversationMessage.objects.create(
            conversation=convo, role="assistant", content=result["reply"],
            sources=result["sources"], question_id=qrow.id,
        )
        # First message names the thread; save() bumps updated_at so it sorts to the top.
        if not convo.title:
            convo.title = content[:60]
        convo.save()
        return Response({
            "message": ConvMessageSerializer(assistant_msg).data,
            "usage": usage_status(operator),
        })
