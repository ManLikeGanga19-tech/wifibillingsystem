from django.urls import path
from rest_framework.routers import SimpleRouter

from .analytics_views import (
    PlatformKpisView,
    PlatformSearchView,
    PlatformTimeseriesView,
    TenantPnlView,
)
from .branding_views import BrandingLogoView, BrandingView, PublicBrandingView
from .domain_views import ChangeDomainView, DomainCheckView, DomainView
from .governance_views import (
    AuditLogViewSet,
    EndImpersonationView,
    ImpersonationViewSet,
    StartImpersonationView,
)
from .health_views import PlatformHealthView
from .settlement_views import ConfirmPayoutView, SettlementView
from .tenant_views import (
    OperatorSettingsView,
    PlatformOverviewView,
    PlatformReconciliationView,
    PlatformTenantViewSet,
    ResetTenantMfaView,
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
    # Branding: how the ISP's business looks to its customers.
    path("operator/branding/", BrandingView.as_view(), name="operator-branding"),
    path("operator/branding/logo/", BrandingLogoView.as_view(), name="operator-branding-logo"),
    # Domain: the address customers reach this ISP at. Changing it re-pushes the captive
    # portal to their routers — see domain_views.
    path("operator/domain/", DomainView.as_view(), name="operator-domain"),
    path("operator/domain/check/", DomainCheckView.as_view(), name="operator-domain-check"),
    path("operator/domain/change/", ChangeDomainView.as_view(), name="operator-domain-change"),
    # Public: the captive portal reads branding to theme itself.
    path("branding/", PublicBrandingView.as_view(), name="public-branding"),
    # Settlement: where we pay the ISP. Registering it is INSTANT and is what
    # switches their payments on; the first payout then carries a code they confirm.
    path("operator/settlement/", SettlementView.as_view(), name="settlement"),
    path(
        "operator/settlement/confirm/",
        ConfirmPayoutView.as_view(),
        name="settlement-confirm",
    ),
    # Public
    path("tenants/signup/", TenantSignupView.as_view(), name="tenant-signup"),
    # Platform-wide (cross-tenant aggregates live ONLY here)
    path("platform/overview/", PlatformOverviewView.as_view(), name="platform-overview"),
    # The lost phone: platform owner clears an ISP owner's authenticator, audited.
    path("platform/reset-mfa/", ResetTenantMfaView.as_view(), name="platform-reset-mfa"),
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
    path("platform/health/", PlatformHealthView.as_view(), name="platform-health"),
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
