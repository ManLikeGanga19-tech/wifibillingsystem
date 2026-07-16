from django.db import transaction as db_transaction
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.tenancy import acting_tenant
from apps.core.viewsets import TenantReadOnlyViewSet, TenantScopedMixin

from .models import Campaign, Channel, Message
from .serializers import CampaignSerializer, MessageSerializer
from .tasks import dispatch_campaign


class CampaignViewSet(
    TenantScopedMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Creating a campaign immediately queues the bulk send."""

    serializer_class = CampaignSerializer
    queryset = Campaign.objects.order_by("-created_at")

    def perform_create(self, serializer):
        super().perform_create(serializer)
        campaign = serializer.instance
        db_transaction.on_commit(lambda: dispatch_campaign.delay(campaign.pk))

    @action(detail=False, methods=["get"])
    def audience(self, request):
        """How many reachable customers each audience resolves to — so the console can show a
        real recipient count and cost BEFORE sending, matching dispatch_campaign's resolution
        exactly (non-blocked subscribers with a contact on this channel)."""
        from apps.accounts.models import Subscriber
        from apps.provisioning.models import Session

        operator = acting_tenant(request)
        channel = request.query_params.get("channel", Channel.SMS)
        base = Subscriber.objects.filter(operator=operator, is_blocked=False)
        base = base.exclude(email="") if channel == Channel.EMAIL else base.exclude(phone="")
        contact = "email" if channel == Channel.EMAIL else "phone"

        def n(qs):
            return qs.values(contact).distinct().count()

        return Response({
            "all": n(base),
            "active": n(base.filter(sessions__status=Session.Status.ACTIVE)),
            "expired": n(
                base.filter(sessions__isnull=False).exclude(
                    sessions__status=Session.Status.ACTIVE
                )
            ),
        })


class MessageViewSet(TenantReadOnlyViewSet):
    serializer_class = MessageSerializer
    queryset = Message.objects.order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        channel = self.request.query_params.get("channel")
        if channel:
            qs = qs.filter(channel=channel)
        return qs
