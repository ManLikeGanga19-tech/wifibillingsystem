from django.urls import path
from rest_framework.routers import SimpleRouter

from .report_views import (
    LedgerCsvView,
    PppoePaymentsCsvView,
    RevenueSummaryView,
    TransactionsCsvView,
)
from .views import LedgerViewSet, MyPayoutsViewSet, PlatformPayoutViewSet, WalletSummaryView

router = SimpleRouter()
router.register("ledger", LedgerViewSet, basename="ledger")
router.register("payouts", MyPayoutsViewSet, basename="payout")
router.register("platform/payouts", PlatformPayoutViewSet, basename="platform-payout")

urlpatterns = [
    path("wallet/", WalletSummaryView.as_view(), name="wallet-summary"),
    # Reports & exports (tenant-scoped).
    path("reports/revenue/", RevenueSummaryView.as_view(), name="report-revenue"),
    path("reports/transactions.csv", TransactionsCsvView.as_view(), name="export-transactions"),
    path("reports/pppoe-payments.csv", PppoePaymentsCsvView.as_view(), name="export-pppoe"),
    path("reports/ledger.csv", LedgerCsvView.as_view(), name="export-ledger"),
    *router.urls,
]
