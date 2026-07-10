from django.db import transaction as db_transaction
from rest_framework import mixins, viewsets

from apps.core.viewsets import TenantReadOnlyViewSet, TenantScopedMixin

from .models import Campaign, Message
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


class MessageViewSet(TenantReadOnlyViewSet):
    serializer_class = MessageSerializer
    queryset = Message.objects.order_by("-created_at")

    def get_queryset(self):
        qs = super().get_queryset()
        channel = self.request.query_params.get("channel")
        if channel:
            qs = qs.filter(channel=channel)
        return qs
