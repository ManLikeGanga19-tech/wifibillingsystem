from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    C2BConfirmationView,
    C2BValidationView,
    DarajaCallbackView,
    STKPushView,
    TransactionStatusView,
    TransactionViewSet,
)

router = SimpleRouter()
router.register("transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("stk-push/", STKPushView.as_view(), name="stk-push"),
    path("status/<uuid:public_id>/", TransactionStatusView.as_view(), name="payment-status"),
    path("callback/<str:token>/", DarajaCallbackView.as_view(), name="daraja-callback"),
    path("c2b/confirmation/<str:token>/", C2BConfirmationView.as_view(), name="c2b-confirmation"),
    path("c2b/validation/<str:token>/", C2BValidationView.as_view(), name="c2b-validation"),
    *router.urls,
]
