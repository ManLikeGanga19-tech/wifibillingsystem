from django.urls import path
from rest_framework.routers import SimpleRouter

from .analytics_views import (
    PlatformKpisView,
    PlatformSearchView,
    PlatformTimeseriesView,
    TenantPnlView,
)
from .governance_views import (
    AuditLogViewSet,
    EndImpersonationView,
    ImpersonationViewSet,
    StartImpersonationView,
)
from .tenant_views import (
    OperatorSettingsView,
    PlatformOverviewView,
    PlatformReconciliationView,
    PlatformTenantViewSet,
    TenantSignupView,
)
from .views import DashboardStatsView, NavCountsView

router = SimpleRouter()
router.register("platform/tenants", PlatformTenantViewSet, basename="platform-tenant")
router.register("platform/audit", AuditLogViewSet, basename="platform-audit")
router.register(
    "platform/impersonation", ImpersonationViewSet, basename="platform-impersonation"
)

urlpatterns = [
    # Tenant-scoped (require an acting ISP)
    path("stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("nav/", NavCountsView.as_view(), name="nav-counts"),
    path("operator/settings/", OperatorSettingsView.as_view(), name="operator-settings"),
    # Public
    path("tenants/signup/", TenantSignupView.as_view(), name="tenant-signup"),
    # Platform-wide (cross-tenant aggregates live ONLY here)
    path("platform/overview/", PlatformOverviewView.as_view(), name="platform-overview"),
    path(
        "platform/reconciliation/",
        PlatformReconciliationView.as_view(),
        name="platform-reconciliation",
    ),
    # Analytics — the Command Center + finance control surface
    path("platform/kpis/", PlatformKpisView.as_view(), name="platform-kpis"),
    path(
        "platform/timeseries/",
        PlatformTimeseriesView.as_view(),
        name="platform-timeseries",
    ),
    path("platform/tenant-pnl/", TenantPnlView.as_view(), name="platform-tenant-pnl"),
    path("platform/search/", PlatformSearchView.as_view(), name="platform-search"),
    # Impersonation is a recorded act, not a header flip — these are the only doors
    path(
        "platform/impersonation/start/",
        StartImpersonationView.as_view(),
        name="impersonation-start",
    ),
    path(
        "platform/impersonation/end/",
        EndImpersonationView.as_view(),
        name="impersonation-end",
    ),
    *router.urls,
]
