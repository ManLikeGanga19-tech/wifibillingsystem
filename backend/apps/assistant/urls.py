from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AIChatView,
    AIProToggleView,
    AIRateView,
    AISettingsView,
    AIUsageView,
    ConversationViewSet,
)

router = SimpleRouter()
router.register("conversations", ConversationViewSet, basename="ai-conversation")

urlpatterns = [
    path("settings/", AISettingsView.as_view(), name="ai-settings"),
    path("chat/", AIChatView.as_view(), name="ai-chat"),
    path("usage/", AIUsageView.as_view(), name="ai-usage"),
    path("pro/", AIProToggleView.as_view(), name="ai-pro-toggle"),
    path("questions/<int:pk>/rate/", AIRateView.as_view(), name="ai-rate"),
    *router.urls,
]
