from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .auth_views import CookieLoginView, CookieRefreshView, LogoutView
from .views import MeView, SubscriberViewSet

router = SimpleRouter()
router.register("subscribers", SubscriberViewSet, basename="subscriber")

urlpatterns = [
    # Browser auth: the server sets httpOnly cookies. The frontends never hold a
    # token, so there is NO browser storage to go stale (see cookie_auth.py).
    path("auth/login/", CookieLoginView.as_view(), name="auth-login"),
    path("auth/refresh/", CookieRefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    # Bearer-token endpoints kept for scripts, tests and the CLI.
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", MeView.as_view(), name="me"),
    *router.urls,
]
