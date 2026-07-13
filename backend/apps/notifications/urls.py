from django.urls import path
from rest_framework.routers import SimpleRouter

from .messaging_views import MessagingSettingsView, MessagingTestView
from .views import CampaignViewSet, MessageViewSet

router = SimpleRouter()
router.register("campaigns", CampaignViewSet, basename="campaign")
router.register("messages", MessageViewSet, basename="message")

urlpatterns = [
    # Which gateway this ISP's messages leave on (Settings > Communications).
    path("settings/", MessagingSettingsView.as_view(), name="messaging-settings"),
    path("settings/test/", MessagingTestView.as_view(), name="messaging-test"),
    *router.urls,
]
