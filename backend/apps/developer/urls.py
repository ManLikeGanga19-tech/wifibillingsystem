from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import ApiTokenViewSet, WebhookEventsView, WebhookViewSet

router = SimpleRouter()
router.register("tokens", ApiTokenViewSet, basename="api-token")
router.register("webhooks", WebhookViewSet, basename="webhook")

urlpatterns = [
    path("webhook-events/", WebhookEventsView.as_view(), name="webhook-events"),
    *router.urls,
]
