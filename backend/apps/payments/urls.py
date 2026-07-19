from django.urls import path
from rest_framework.routers import SimpleRouter

from .gateway_views import (
    ActivateGatewayView,
    ConfigureGatewayView,
    GatewayWebhookView,
    PaymentGatewaysView,
    TestGatewayView,
)
from .views import (
    C2BConfirmationView,
    C2BValidationView,
    DarajaCallbackView,
    DeviceStatusView,
    PaymentSearchView,
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
    path("search/", PaymentSearchView.as_view(), name="payment-search"),
    path("stk-push/", STKPushView.as_view(), name="stk-push"),
    path("device-status/", DeviceStatusView.as_view(), name="device-status"),
    path("status/<uuid:public_id>/", TransactionStatusView.as_view(), name="payment-status"),
    path(
        "status/<uuid:public_id>/retry/",
        RetryProvisionView.as_view(),
        name="payment-retry-provision",
    ),
    # The PLATFORM paybill's callback (the aggregator). One URL, every tenant — the
    # transaction is matched on CheckoutRequestID. Kept as-is so the shortcode already
    # registered with Safaricom keeps working.
    path("callback/<str:token>/", DarajaCallbackView.as_view(), name="daraja-callback"),
    # An ISP's OWN gateway. The token is theirs: it names the operator AND authenticates
    # the call, so a guessed URL cannot forge a paid session.
    path(
        "hooks/<str:gateway_id>/<str:token>/",
        GatewayWebhookView.as_view(),
        name="gateway-webhook",
    ),
    # Settings > Payments
    path("gateways/", PaymentGatewaysView.as_view(), name="payment-gateways"),
    path(
        "gateways/<str:gateway_id>/",
        ConfigureGatewayView.as_view(),
        name="payment-gateway-configure",
    ),
    path(
        "gateways/<str:gateway_id>/activate/",
        ActivateGatewayView.as_view(),
        name="payment-gateway-activate",
    ),
    path(
        "gateways/<str:gateway_id>/test/",
        TestGatewayView.as_view(),
        name="payment-gateway-test",
    ),
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
