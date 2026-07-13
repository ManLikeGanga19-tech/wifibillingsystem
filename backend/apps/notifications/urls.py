from django.urls import path
from rest_framework.routers import SimpleRouter

from .messaging_views import (
    ActivateProviderView,
    ConfigureProviderView,
    DisconnectProviderView,
    EmailSettingsView,
    MessagingTestView,
    ProvidersView,
)
from .views import CampaignViewSet, MessageViewSet

router = SimpleRouter()
router.register("campaigns", CampaignViewSet, basename="campaign")
router.register("messages", MessageViewSet, basename="message")

urlpatterns = [
    # Settings > Communications: which gateway this ISP's messages leave on.
    path("settings/email/", EmailSettingsView.as_view(), name="messaging-email"),
    path("settings/test/", MessagingTestView.as_view(), name="messaging-test"),
    path("settings/<str:channel>/", ProvidersView.as_view(), name="messaging-providers"),
    path(
        "settings/<str:channel>/<str:provider_id>/",
        ConfigureProviderView.as_view(),
        name="messaging-provider-configure",
    ),
    path(
        "settings/<str:channel>/<str:provider_id>/activate/",
        ActivateProviderView.as_view(),
        name="messaging-provider-activate",
    ),
    path(
        "settings/<str:channel>/<str:provider_id>/disconnect/",
        DisconnectProviderView.as_view(),
        name="messaging-provider-disconnect",
    ),
    *router.urls,
]
