from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import LedgerViewSet, MyPayoutsViewSet, PlatformPayoutViewSet, WalletSummaryView

router = SimpleRouter()
router.register("ledger", LedgerViewSet, basename="ledger")
router.register("payouts", MyPayoutsViewSet, basename="payout")
router.register("platform/payouts", PlatformPayoutViewSet, basename="platform-payout")

urlpatterns = [
    path("wallet/", WalletSummaryView.as_view(), name="wallet-summary"),
    *router.urls,
]
