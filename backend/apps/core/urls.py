from django.urls import path
from rest_framework.routers import SimpleRouter

from .tenant_views import (
    OperatorSettingsView,
    PlatformTenantViewSet,
    TenantSignupView,
)
from .views import DashboardStatsView, NavCountsView

router = SimpleRouter()
router.register("platform/tenants", PlatformTenantViewSet, basename="platform-tenant")

urlpatterns = [
    path("stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("nav/", NavCountsView.as_view(), name="nav-counts"),
    path("tenants/signup/", TenantSignupView.as_view(), name="tenant-signup"),
    path("operator/settings/", OperatorSettingsView.as_view(), name="operator-settings"),
    *router.urls,
]
