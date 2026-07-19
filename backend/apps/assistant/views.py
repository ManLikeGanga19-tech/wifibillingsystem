"""Settings > AI Assistant: configure the provider + optional BYO key, and the chat endpoint."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import (
    NotBillingLocked,
    ReadOnlyForSupport,
    RequireTenant,
    TenantIsOperational,
)
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant

from .models import Provider
from .providers import (
    AssistantError,
    AssistantUnavailable,
    chat,
    platform_default_provider,
    platform_key_configured,
    settings_for,
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


class ChatSerializer(serializers.Serializer):
    messages = serializers.ListField(child=serializers.DictField(), allow_empty=False)


class AIChatView(APIView):
    """One turn of the dashboard assistant."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(
        request=ChatSerializer, responses=OBJECT_RESPONSE, summary="Ask the AI assistant",
    )
    def post(self, request):
        s = ChatSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = acting_tenant(request)
        try:
            reply = chat(operator, s.validated_data["messages"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except AssistantUnavailable as exc:
            return Response({"detail": str(exc), "code": "not_configured"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except AssistantError as exc:
            return Response({"detail": str(exc), "code": "provider_error"},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response({"reply": reply})
