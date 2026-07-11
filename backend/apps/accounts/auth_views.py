"""Auth endpoints that keep the session on the SERVER, not in the browser.

The frontends never see or store a token: they POST credentials, the server sets
httpOnly cookies, and every later request is authenticated by the browser
automatically. Logging out clears the cookies. There is nothing in localStorage
to go stale, and nothing for a user to "clear their cache" to fix.
"""

from django.middleware.csrf import get_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .cookie_auth import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)


class CookieLoginView(APIView):
    """POST {phone, password} -> httpOnly cookies. Returns no token in the body:
    if JavaScript can't read it, XSS can't steal it."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return Response(
                {"detail": "Wrong phone number or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        data = serializer.validated_data
        # Hand the client a CSRF token to echo back on future writes. It is a
        # readable cookie ON PURPOSE (double-submit): an attacker's site cannot read
        # it cross-origin, so they cannot forge the X-CSRFToken header.
        csrf_token = get_token(request)
        resp = Response({"detail": "Signed in.", "csrf_token": csrf_token})
        return set_auth_cookies(resp, access=str(data["access"]), refresh=str(data["refresh"]))


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


class LogoutView(APIView):
    """Clear every cookie we set — including any acting-tenant."""

    permission_classes = [AllowAny]

    def post(self, request):
        return clear_auth_cookies(Response({"detail": "Signed out."}))
