from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health(_request):
    """Readiness probe — unauthenticated, cheap. 200 only if the app is up AND the DB is
    reachable, so a load balancer / container health check routes only to replicas that can
    actually serve, and the console's reconnect probe knows when the API is truly back."""
    from django.db import connection

    try:
        connection.ensure_connection()
    except Exception:
        return JsonResponse({"status": "db-unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


api_v1 = [
    path("health/", health, name="health"),
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.plans.urls")),
    path("payments/", include("apps.payments.urls")),
    path("", include("apps.provisioning.urls")),
    path("vouchers/", include("apps.vouchers.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("ops/", include("apps.ops.urls")),
    path("billing/", include("apps.billing.urls")),
    path("pppoe/", include("apps.pppoe.urls")),
    path("loyalty/", include("apps.loyalty.urls")),
    path("fibre/", include("apps.fibre.urls")),
    path("fleet/", include("apps.fleet.urls")),
    path("", include("apps.maps.urls")),
    path("assistant/", include("apps.assistant.urls")),
    path("developer/", include("apps.developer.urls")),
    # The 5-step ISP signup. Entirely anonymous; the draft lives on the SERVER,
    # behind an httpOnly cookie (no browser storage anywhere).
    path("signup/", include("apps.signup.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1)),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
