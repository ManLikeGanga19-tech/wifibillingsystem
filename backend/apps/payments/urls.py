from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    C2BConfirmationView,
    C2BValidationView,
    DarajaCallbackView,
    DeviceStatusView,
    ResolveUnmatchedView,
    RetryProvisionView,
    STKPushView,
    TransactionStatusView,
    TransactionViewSet,
    UnmatchedPaymentsView,
)

router = SimpleRouter()
router.register("transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("stk-push/", STKPushView.as_view(), name="stk-push"),
    path("device-status/", DeviceStatusView.as_view(), name="device-status"),
    path("status/<uuid:public_id>/", TransactionStatusView.as_view(), name="payment-status"),
    path(
        "status/<uuid:public_id>/retry/",
        RetryProvisionView.as_view(),
        name="payment-retry-provision",
    ),
    path("callback/<str:token>/", DarajaCallbackView.as_view(), name="daraja-callback"),
    path("c2b/confirmation/<str:token>/", C2BConfirmationView.as_view(), name="c2b-confirmation"),
    path("c2b/validation/<str:token>/", C2BValidationView.as_view(), name="c2b-validation"),
    # The unmatched-payments queue (platform staff): money that landed on a mistyped
    # account number, and the tool to reunite it with its client.
    path("platform/unmatched/", UnmatchedPaymentsView.as_view(), name="unmatched-payments"),
    path(
        "platform/unmatched/<int:pk>/resolve/",
        ResolveUnmatchedView.as_view(),
        name="resolve-unmatched",
    ),
    *router.urls,
]
