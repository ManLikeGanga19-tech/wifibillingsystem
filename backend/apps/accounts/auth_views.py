"""Auth endpoints that keep the session on the SERVER, not in the browser.

The frontends never see or store a token: they POST credentials, the server sets
httpOnly cookies, and every later request is authenticated by the browser
automatically. Logging out clears the cookies. There is nothing in localStorage
to go stale, and nothing for a user to "clear their cache" to fix.
"""

import logging

from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.phone import InvalidPhoneError, normalize_msisdn
from apps.core.schema import (
    OBJECT_RESPONSE,
    DetailSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
)
from apps.core.services import audit

from .cookie_auth import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)

logger = logging.getLogger(__name__)


def resolve_identifier(raw: str) -> str:
    """Phone OR email in, the login username (phone) out.

    Two identifiers, one account. An ISP signs up with an email and never types a
    phone number again, so making them remember which one we wanted at the login box
    is a self-inflicted support ticket.

    It is NOT an enumeration oracle: an unknown email resolves to the raw string,
    which then fails authentication exactly like a wrong password — same response,
    same timing shape. We never say "no such account".
    """
    from .models import User

    ident = (raw or "").strip()
    if "@" in ident:
        match = User.objects.filter(email__iexact=ident).values_list("phone", flat=True).first()
        return match or ident
    try:
        # 0712…, +254712…, 712… — all the same account. A number they cannot dial
        # wrong is a number they cannot fail to log in with.
        return normalize_msisdn(ident)
    except InvalidPhoneError:
        # Garbage is not a 500 — it is a failed login, handled like any other.
        return ident


# ---- brute force ---------------------------------------------------------------
#
# TWO limits, because each one alone is trivially bypassed:
#
#   PER IP (the `login` DRF throttle, 10/min) stops one machine grinding through a
#   dictionary. An attacker with a botnet — or a single ISP behind CGNAT — walks past it.
#
#   PER ACCOUNT (below) stops the botnet. It also means an attacker spraying ONE common
#   password across every account we have gets one attempt per account per window,
#   which is the attack that actually works against real user passwords.
#
# The lockout is on the ACCOUNT IDENTIFIER, not the session, and lives in Redis so it
# survives a deploy and is shared across every worker.
LOCKOUT_THRESHOLD = 10
LOCKOUT_MINUTES = 15


def _lock_key(identifier: str) -> str:
    return f"login-fail:{identifier.lower()}"


def _is_locked(identifier: str) -> bool:
    return cache.get(_lock_key(identifier), 0) >= LOCKOUT_THRESHOLD


def _record_failure(identifier: str) -> None:
    key = _lock_key(identifier)
    try:
        count = cache.incr(key)
    except ValueError:  # first failure — incr on a missing key raises
        cache.set(key, 1, timeout=LOCKOUT_MINUTES * 60)
        count = 1
    if count >= LOCKOUT_THRESHOLD:
        logger.warning("Login locked out for %s after %s failures", identifier, count)


def _clear_failures(identifier: str) -> None:
    cache.delete(_lock_key(identifier))


@extend_schema(
    request=LoginRequestSerializer,
    responses={200: LoginResponseSerializer, 401: DetailSerializer},
    summary="Sign in with phone or email (sets httpOnly cookies; no token in the body)",
)
class CookieLoginView(APIView):
    """POST {phone, password} -> httpOnly cookies. `phone` accepts an email address
    too. Returns no token in the body: if JavaScript can't read it, XSS can't steal
    it."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        identifier = resolve_identifier(
            str(request.data.get("phone") or request.data.get("email") or "")
        )

        if _is_locked(identifier):
            # Deliberately says "too many attempts" rather than "wrong password": at
            # this point we are talking to an attacker, and there is nothing left to
            # protect by pretending otherwise. The real owner is told what to do.
            return Response(
                {
                    "detail": (
                        f"Too many failed attempts. Try again in {LOCKOUT_MINUTES} "
                        "minutes, or reset your password."
                    )
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        credentials = {
            "phone": identifier,
            "password": request.data.get("password") or "",
        }
        serializer = TokenObtainPairSerializer(data=credentials)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            _record_failure(identifier)
            return Response(
                # Deliberately one message for both fields and both identifiers —
                # naming which half was wrong tells an attacker which half was right.
                {"detail": "Wrong phone/email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        _clear_failures(identifier)
        tokens = serializer.validated_data
        # Hand the client a CSRF token to echo back on future writes. It is a
        # readable cookie ON PURPOSE (double-submit): an attacker's site cannot read
        # it cross-origin, so they cannot forge the X-CSRFToken header.
        csrf_token = get_token(request)
        resp = Response({"detail": "Signed in.", "csrf_token": csrf_token})
        return set_auth_cookies(
            resp, access=str(tokens["access"]), refresh=str(tokens["refresh"])
        )


@extend_schema(request=None, responses={200: DetailSerializer, 401: DetailSerializer},
               summary="Silently renew the access cookie")
class CookieRefreshView(APIView):
    """Silently renew the access cookie from the refresh cookie."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.COOKIES.get(REFRESH_COOKIE)
        if not raw:
            return Response(
                {"detail": "Not signed in."}, status=status.HTTP_401_UNAUTHORIZED
            )
        try:
            refresh = RefreshToken(raw)
        except TokenError:
            # Expired/garbage refresh: clear the cookies so the browser stops
            # replaying a dead session forever.
            resp = Response(
                {"detail": "Session expired."}, status=status.HTTP_401_UNAUTHORIZED
            )
            return clear_auth_cookies(resp)
        resp = Response({"detail": "Refreshed."})
        return set_auth_cookies(resp, access=str(refresh.access_token))


@extend_schema(request=None, responses={200: DetailSerializer},
               summary="Sign out (clears every cookie we set)")
class LogoutView(APIView):
    """Clear every cookie we set — including any acting-tenant."""

    permission_classes = [AllowAny]

    def post(self, request):
        return clear_auth_cookies(Response({"detail": "Signed out."}))


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()


@extend_schema(request=ChangePasswordSerializer, responses=OBJECT_RESPONSE,
               summary="Change your password (needs the current one)")
class ChangePasswordView(APIView):
    """Change the signed-in user's password. Requires the current password (so a walk-up on an
    unlocked console can't lock the owner out), and runs Django's password validators plus a hard
    minimum on the new one. Not 2FA-gated — that's for MONEY, not account maintenance.

    On success we re-issue fresh cookies: the old JWTs stay valid until they expire (they're
    stateless), so rotating them is the clean way to make "changed my password" mean something.
    """

    permission_classes = [IsAuthenticated]
    MIN_LENGTH = 8

    def post(self, request):
        s = ChangePasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = request.user

        if not user.check_password(s.validated_data["current_password"]):
            return Response(
                {"detail": "That is not your current password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_password = s.validated_data["new_password"]
        # A floor that holds even if no AUTH_PASSWORD_VALIDATORS are configured.
        if len(new_password) < self.MIN_LENGTH:
            return Response(
                {"detail": f"Use at least {self.MIN_LENGTH} characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=["password"])
        audit("password_changed", operator=getattr(user, "operator", None), actor=user, target=user)

        # Keep them signed in on THIS session, on freshly-minted tokens.
        refresh = RefreshToken.for_user(user)
        resp = Response({"detail": "Your password was changed."})
        return set_auth_cookies(resp, access=str(refresh.access_token), refresh=str(refresh))
