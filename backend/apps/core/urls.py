from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.assistant.views import PlatformAISettingsView, PlatformDocsGapsView

from .analytics_views import (
    PlatformCohortRetentionView,
    PlatformKpisView,
    PlatformMrrMovementView,
    PlatformOnboardingFunnelView,
    PlatformRiskView,
    PlatformSearchView,
    PlatformTimeseriesView,
    TenantPnlView,
)
from .branding_views import (
    BrandingBackgroundView,
    BrandingLogoView,
    BrandingView,
    PublicBrandingView,
)
from .broadcast_views import (
    ActiveBroadcastsView,
    DismissBroadcastView,
    PlatformBroadcastViewSet,
)
from .domain_views import ChangeDomainView, DomainCheckView, DomainView
from .governance_views import (
    AuditLogViewSet,
    EndImpersonationView,
    ImpersonationViewSet,
    StartImpersonationView,
)
from .health_views import PlatformHealthView
from .hotspot_settings_views import HotspotSettingsView
from .settlement_views import ConfirmPayoutView, SettlementView
from .tenant_views import (
    OperatorSettingsView,
    PlatformOverviewView,
    PlatformReconciliationView,
    PlatformTenantViewSet,
    ResetTenantMfaView,
    TenantSignupView,
)
from .views import DashboardStatsView, LiveConnectionsView, NavCountsView

router = SimpleRouter()
router.register("platform/tenants", PlatformTenantViewSet, basename="platform-tenant")
router.register("platform/audit", AuditLogViewSet, basename="platform-audit")
router.register(
    "platform/impersonation", ImpersonationViewSet, basename="platform-impersonation"
)
router.register("platform/broadcasts", PlatformBroadcastViewSet, basename="platform-broadcast")

urlpatterns = [
    # Tenant-scoped (require an acting ISP)
    path("stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("nav/", NavCountsView.as_view(), name="nav-counts"),
    path("live-connections/", LiveConnectionsView.as_view(), name="live-connections"),
    path("operator/settings/", OperatorSettingsView.as_view(), name="operator-settings"),
    # Branding: how the ISP's business looks to its customers.
    path("operator/branding/", BrandingView.as_view(), name="operator-branding"),
    path("operator/branding/logo/", BrandingLogoView.as_view(), name="operator-branding-logo"),
    path(
        "operator/branding/background/",
        BrandingBackgroundView.as_view(),
        name="operator-branding-background",
    ),
    # Hotspot: the captive-portal subscriber lifecycle (clock start, prune, prefix, vouchers).
    path("operator/hotspot/", HotspotSettingsView.as_view(), name="operator-hotspot-settings"),
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
    # Broadcasts shown IN the ISP console — any signed-in user, audience is every tenant.
    path("broadcasts/active/", ActiveBroadcastsView.as_view(), name="broadcasts-active"),
    path("broadcasts/<int:pk>/dismiss/", DismissBroadcastView.as_view(),
         name="broadcasts-dismiss"),
    # Public
    path("tenants/signup/", TenantSignupView.as_view(), name="tenant-signup"),
    # Platform-wide (cross-tenant aggregates live ONLY here)
    path("platform/overview/", PlatformOverviewView.as_view(), name="platform-overview"),
    # The cross-tenant AI key + platform-wide rate limit (owner-only, lives in the assistant app).
    path("platform/ai-settings/", PlatformAISettingsView.as_view(), name="platform-ai-settings"),
    # The docs-gaps report — cross-tenant, anonymised assistant analytics.
    path("platform/ai-docs-gaps/", PlatformDocsGapsView.as_view(), name="platform-ai-docs-gaps"),
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
    path("platform/mrr-movement/", PlatformMrrMovementView.as_view(), name="platform-mrr-movement"),
    path("platform/onboarding-funnel/", PlatformOnboardingFunnelView.as_view(),
         name="platform-onboarding-funnel"),
    path("platform/cohort-retention/", PlatformCohortRetentionView.as_view(),
         name="platform-cohort-retention"),
    path("platform/risk/", PlatformRiskView.as_view(), name="platform-risk"),
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
