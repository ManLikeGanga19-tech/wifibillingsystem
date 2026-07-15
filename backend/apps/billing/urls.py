from django.urls import path
from rest_framework.routers import SimpleRouter

from .report_views import (
    LedgerCsvView,
    PppoePaymentsCsvView,
    RevenueSummaryView,
    TransactionsCsvView,
)
from .topup_views import (
    LowBalanceAlertView,
    PlatformAccountView,
    PlatformInvoicesView,
    TopUpCallbackView,
    TopUpStatusView,
    TopUpView,
)
from .views import LedgerViewSet, MyPayoutsViewSet, PlatformPayoutViewSet, WalletSummaryView

router = SimpleRouter()
router.register("ledger", LedgerViewSet, basename="ledger")
router.register("payouts", MyPayoutsViewSet, basename="payout")
router.register("platform/payouts", PlatformPayoutViewSet, basename="platform-payout")

urlpatterns = [
    path("wallet/", WalletSummaryView.as_view(), name="wallet-summary"),
    # The ISP's account WITH US: what they owe, and topping it up by STK.
    path("account/", PlatformAccountView.as_view(), name="platform-account"),
    path("account/alerts/", LowBalanceAlertView.as_view(), name="platform-account-alerts"),
    path("account/invoices/", PlatformInvoicesView.as_view(), name="platform-invoices"),
    path("topup/", TopUpView.as_view(), name="topup"),
    path("topup/<int:pk>/", TopUpStatusView.as_view(), name="topup-status"),
    # Its OWN callback — this money flows the other way and must never be mistaken for a
    # subscriber payment.
    path("topup/callback/<str:token>/", TopUpCallbackView.as_view(), name="topup-callback"),
    # Reports & exports (tenant-scoped).
    path("reports/revenue/", RevenueSummaryView.as_view(), name="report-revenue"),
    path("reports/transactions.csv", TransactionsCsvView.as_view(), name="export-transactions"),
    path("reports/pppoe-payments.csv", PppoePaymentsCsvView.as_view(), name="export-pppoe"),
    path("reports/ledger.csv", LedgerCsvView.as_view(), name="export-ledger"),
    *router.urls,
]
