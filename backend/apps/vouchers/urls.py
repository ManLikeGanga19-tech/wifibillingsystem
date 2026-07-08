from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import RedeemVoucherView, VoucherViewSet

router = SimpleRouter()
router.register("", VoucherViewSet, basename="voucher")

urlpatterns = [
    path("redeem/", RedeemVoucherView.as_view(), name="voucher-redeem"),
    *router.urls,
]
