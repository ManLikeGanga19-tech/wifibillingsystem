from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import DarajaCallbackView, STKPushView, TransactionStatusView, TransactionViewSet

router = SimpleRouter()
router.register("transactions", TransactionViewSet, basename="transaction")

urlpatterns = [
    path("stk-push/", STKPushView.as_view(), name="stk-push"),
    path("status/<uuid:public_id>/", TransactionStatusView.as_view(), name="payment-status"),
    path("callback/<str:token>/", DarajaCallbackView.as_view(), name="daraja-callback"),
    *router.urls,
]
