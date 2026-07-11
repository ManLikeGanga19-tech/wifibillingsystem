from django.urls import path
from rest_framework.routers import SimpleRouter

from .tenant_views import (
    OperatorSettingsView,
    PlatformOverviewView,
    PlatformTenantViewSet,
    TenantSignupView,
)
from .views import DashboardStatsView, NavCountsView

router = SimpleRouter()
router.register("platform/tenants", PlatformTenantViewSet, basename="platform-tenant")

urlpatterns = [
    # Tenant-scoped (require an acting ISP)
    path("stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("nav/", NavCountsView.as_view(), name="nav-counts"),
    path("operator/settings/", OperatorSettingsView.as_view(), name="operator-settings"),
    # Public
    path("tenants/signup/", TenantSignupView.as_view(), name="tenant-signup"),
    # Platform-wide (cross-tenant aggregates live ONLY here)
    path("platform/overview/", PlatformOverviewView.as_view(), name="platform-overview"),
    *router.urls,
]
