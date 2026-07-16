from django.urls import path

from .views import LoyaltySettingsView, LoyaltySummaryView

urlpatterns = [
    path("settings/", LoyaltySettingsView.as_view(), name="loyalty-settings"),
    path("summary/", LoyaltySummaryView.as_view(), name="loyalty-summary"),
]
