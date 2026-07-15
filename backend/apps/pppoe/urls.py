from django.urls import path
from rest_framework.routers import SimpleRouter

from .settings_views import PppoeSettingsView
from .views import (
    AccessPointViewSet,
    ClientViewSet,
    InvoiceViewSet,
    PppoeUsageSummaryView,
    ServicePlanViewSet,
    SuspendedNoticeView,
    TowerViewSet,
    account_lookup,
)

router = SimpleRouter()
router.register("plans", ServicePlanViewSet, basename="pppoe-plan")
router.register("clients", ClientViewSet, basename="pppoe-client")
router.register("invoices", InvoiceViewSet, basename="pppoe-invoice")
router.register("towers", TowerViewSet, basename="pppoe-tower")
router.register("access-points", AccessPointViewSet, basename="pppoe-ap")

urlpatterns = [
    path("settings/", PppoeSettingsView.as_view(), name="pppoe-settings"),
    path("usage-summary/", PppoeUsageSummaryView.as_view(), name="pppoe-usage-summary"),
    path("suspended-notice/", SuspendedNoticeView.as_view(), name="pppoe-suspended-notice"),
    path("account-lookup/", account_lookup, name="pppoe-account-lookup"),
    *router.urls,
]
