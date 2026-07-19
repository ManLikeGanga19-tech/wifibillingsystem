from django.urls import path

from .views import AIChatView, AISettingsView

urlpatterns = [
    path("settings/", AISettingsView.as_view(), name="ai-settings"),
    path("chat/", AIChatView.as_view(), name="ai-chat"),
]
