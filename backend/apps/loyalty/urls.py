from django.urls import path

from .views import (
    LoyaltyAccountView,
    LoyaltyAdjustView,
    LoyaltyRedeemView,
    LoyaltySettingsView,
    LoyaltySummaryView,
)

urlpatterns = [
    path("settings/", LoyaltySettingsView.as_view(), name="loyalty-settings"),
    path("summary/", LoyaltySummaryView.as_view(), name="loyalty-summary"),
    path("account/", LoyaltyAccountView.as_view(), name="loyalty-account"),
    path("redeem/", LoyaltyRedeemView.as_view(), name="loyalty-redeem"),
    path("adjust/", LoyaltyAdjustView.as_view(), name="loyalty-adjust"),
]
