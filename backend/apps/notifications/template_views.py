"""Settings > Message templates: the ISP edits the body of each automated customer SMS.

Read returns the whole catalogue (registry defaults + this ISP's overrides + the variable
allow-lists the console renders as chips). Write validates against the same allow-list, so a
typo'd @variable can never be saved and later sent to a customer as literal text.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
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

from . import templates as reg
from .models import MessageTemplate

BODY_MAX = 640  # ~4 SMS segments; matches the model field + the send-path hard cap


def _rows(operator) -> list:
    overrides = {
        t.key: t
        for t in MessageTemplate.objects.filter(operator=operator)
    }
    out = []
    for group in reg.GROUP_ORDER:
        for key, tpl in reg.TEMPLATES.items():
            if tpl.group != group:
                continue
            row = overrides.get(key)
            customized = row is not None and row.body.strip() != ""
            out.append({
                "key": key,
                "group": tpl.group,
                "label": tpl.label,
                "description": tpl.description,
                "default_body": tpl.default_body,
                "body": (row.body if customized else tpl.default_body),
                "is_customized": customized,
                "is_enabled": row.is_enabled if row is not None else True,
                "variables": [{"name": n, "sample": s} for n, s in tpl.variables],
            })
    return out


class TemplateUpdateSerializer(serializers.Serializer):
    key = serializers.CharField()
    body = serializers.CharField(required=False, allow_blank=True, max_length=BODY_MAX)
    is_enabled = serializers.BooleanField(required=False)

    def validate_key(self, value):
        if reg.get_template(value) is None:
            raise serializers.ValidationError("Unknown template.")
        return value

    def validate(self, attrs):
        body = attrs.get("body")
        if body:
            bad = reg.unknown_tokens(attrs["key"], body)
            if bad:
                raise serializers.ValidationError(
                    {"body": f"Unknown variable(s): {', '.join('@' + b for b in bad)}. "
                             "Use only the variables listed under this message."}
                )
        return attrs


class MessageTemplatesView(APIView):
    """Read the catalogue; update one template."""

    permission_classes = [
        IsAdminUser, RequireTenant, TenantIsOperational, ReadOnlyForSupport, NotBillingLocked,
    ]

    @extend_schema(responses=OBJECT_RESPONSE, summary="This ISP's automated SMS templates")
    def get(self, request):
        operator = acting_tenant(request)
        return Response({"groups": reg.GROUP_ORDER, "templates": _rows(operator)})

    @extend_schema(
        request=TemplateUpdateSerializer, responses=OBJECT_RESPONSE,
        summary="Update one automated SMS template (body / enabled)",
    )
    def patch(self, request):
        s = TemplateUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        operator = acting_tenant(request)

        row, _ = MessageTemplate.objects.get_or_create(operator=operator, key=data["key"])
        if "body" in data:
            row.body = data["body"]
        if "is_enabled" in data:
            row.is_enabled = data["is_enabled"]
        row.save()
        audit(
            "message_template_updated", operator=operator, actor=request.user,
            target=operator, template=data["key"],
        )
        return Response({"groups": reg.GROUP_ORDER, "templates": _rows(operator)})
