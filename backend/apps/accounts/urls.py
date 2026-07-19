from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .auth_views import ChangePasswordView, CookieLoginView, CookieRefreshView, LogoutView
from .mfa_views import (
    MfaConfirmView,
    MfaDisableView,
    MfaRecoveryCodesView,
    MfaSetupView,
    MfaStatusView,
)
from .views import MeView, SubscriberViewSet

router = SimpleRouter()
router.register("subscribers", SubscriberViewSet, basename="subscriber")

urlpatterns = [
    # Two-factor for the actions that move money (withdrawals, changing the payout
    # account). NOT for login — losing a phone must cost an ISP their payouts, not
    # their whole console.
    path("auth/mfa/", MfaStatusView.as_view(), name="mfa-status"),
    path("auth/mfa/setup/", MfaSetupView.as_view(), name="mfa-setup"),
    path("auth/mfa/confirm/", MfaConfirmView.as_view(), name="mfa-confirm"),
    path("auth/mfa/recovery-codes/", MfaRecoveryCodesView.as_view(), name="mfa-recovery"),
    path("auth/mfa/disable/", MfaDisableView.as_view(), name="mfa-disable"),
    # Browser auth: the server sets httpOnly cookies. The frontends never hold a
    # token, so there is NO browser storage to go stale (see cookie_auth.py).
    path("auth/login/", CookieLoginView.as_view(), name="auth-login"),
    path("auth/refresh/", CookieRefreshView.as_view(), name="auth-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    # Bearer-token endpoints kept for scripts, tests and the CLI.
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("me/", MeView.as_view(), name="me"),
    *router.urls,
]
