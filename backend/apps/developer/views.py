"""Settings > Developer: API tokens + webhooks management, and the events catalog."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequireTenant, TenantIsOperational
from apps.core.schema import OBJECT_RESPONSE
from apps.core.services import audit
from apps.core.tenancy import acting_tenant
from apps.core.viewsets import TenantModelViewSet

from .events import WEBHOOK_EVENTS
from .models import ApiToken, Webhook, generate_token
from .serializers import ApiTokenSerializer, WebhookSerializer


class ApiTokenViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """List live tokens, mint one (plaintext shown ONCE), revoke one."""

    serializer_class = ApiTokenSerializer
    permission_classes = TenantModelViewSet.permission_classes
    queryset = ApiToken.objects.all()

    def get_operator(self):
        return acting_tenant(self.request)

    def get_queryset(self):
        # Live tokens only. Revoked rows are kept (for the last-used audit trail) but hidden.
        return ApiToken.objects.filter(
            operator=self.get_operator(), revoked_at__isnull=True
        )

    @extend_schema(
        request=ApiTokenSerializer, responses=OBJECT_RESPONSE,
        summary="Create an API token (plaintext returned once)",
    )
    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        operator = self.get_operator()
        plaintext, token_hash, prefix = generate_token()
        token = ApiToken.objects.create(
            operator=operator, created_by=request.user, name=s.validated_data["name"],
            prefix=prefix, token_hash=token_hash,
        )
        audit("api_token_created", operator=operator, actor=request.user, target=operator,
              name=token.name, prefix=prefix)
        # The ONE time the plaintext is ever exposed — the console tells the user to copy it now.
        return Response(
            {**ApiTokenSerializer(token).data, "token": plaintext},
            status=201,
        )

    def perform_destroy(self, instance):
        # Soft revoke: keep the row so "who used what, last" survives, but the token stops working.
        instance.revoked_at = timezone.now()
        instance.save(update_fields=["revoked_at"])
        audit("api_token_revoked", operator=self.get_operator(), actor=self.request.user,
              target=self.get_operator(), name=instance.name, prefix=instance.prefix)


class WebhookViewSet(TenantModelViewSet):
    """CRUD over an ISP's outbound webhooks."""

    serializer_class = WebhookSerializer
    queryset = Webhook.objects.all()

    def create(self, request, *args, **kwargs):
        resp = super().create(request, *args, **kwargs)
        # Reveal the (possibly auto-generated) signing secret ONCE, so the ISP can store it to
        # verify our signatures. After this it's only ever shown masked.
        hook = Webhook.objects.get(pk=resp.data["id"])
        resp.data["secret"] = hook.secret
        return resp

    def perform_create(self, serializer):
        super().perform_create(serializer)
        audit("webhook_created", operator=self.get_operator(), actor=self.request.user,
              target=self.get_operator(), label=serializer.instance.label,
              url=serializer.instance.url)

    def perform_destroy(self, instance):
        audit("webhook_deleted", operator=self.get_operator(), actor=self.request.user,
              target=self.get_operator(), label=instance.label)
        instance.delete()


class WebhookEventsView(APIView):
    """The catalog of events an ISP can subscribe a webhook to."""

    permission_classes = [IsAdminUser, RequireTenant, TenantIsOperational]

    @extend_schema(responses=OBJECT_RESPONSE, summary="Available webhook events")
    def get(self, request):
        return Response({"events": [{"key": k, "label": v} for k, v in WEBHOOK_EVENTS]})
