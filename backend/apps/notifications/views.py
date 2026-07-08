from django.db import transaction as db_transaction
from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAdminUser

from apps.core.services import get_default_operator

from .models import Campaign, Message
from .serializers import CampaignSerializer, MessageSerializer
from .tasks import dispatch_campaign


class CampaignViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Creating a campaign immediately queues the bulk send."""

    permission_classes = [IsAdminUser]
    serializer_class = CampaignSerializer
    queryset = Campaign.objects.order_by("-created_at")

    def perform_create(self, serializer):
        campaign = serializer.save(
            operator=get_default_operator(), created_by=self.request.user
        )
        db_transaction.on_commit(lambda: dispatch_campaign.delay(campaign.pk))


class MessageViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAdminUser]
    serializer_class = MessageSerializer
    queryset = Message.objects.order_by("-created_at")
