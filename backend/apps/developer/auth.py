"""Authenticate a request by its API token (`Authorization: Token wos_…`).

Runs AFTER CookieJWTAuthentication in the auth chain: a Bearer/cookie request is handled there and
this class only sees requests carrying the `Token` scheme. A token acts as the user who created it,
scoped to that user's tenant — so a tenant-owner token reaches exactly the tenant API their login
does, and platform endpoints (IsPlatformStaff) stay closed to it.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiToken, hash_token

#: Don't write last_used_at on every call — once a minute is plenty to answer "is this token live?".
_TOUCH_EVERY = timedelta(minutes=1)


class ApiTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None  # not a Token request — let other authenticators try
        if len(auth) == 1:
            raise exceptions.AuthenticationFailed("Invalid token header: no credentials provided.")
        if len(auth) > 2:
            raise exceptions.AuthenticationFailed("Invalid token header: token has spaces.")

        try:
            plaintext = auth[1].decode()
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed("Invalid token header encoding.") from exc

        token = (
            ApiToken.objects.select_related("operator", "created_by")
            .filter(token_hash=hash_token(plaintext), revoked_at__isnull=True)
            .first()
        )
        if token is None:
            raise exceptions.AuthenticationFailed("Invalid or revoked API token.")

        user = token.created_by
        if user is None or not user.is_active:
            raise exceptions.AuthenticationFailed("The token's owner is no longer active.")

        self._touch(token)
        return (user, token)

    def authenticate_header(self, request):
        return self.keyword

    @staticmethod
    def _touch(token: ApiToken) -> None:
        now = timezone.now()
        if token.last_used_at is None or now - token.last_used_at >= _TOUCH_EVERY:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
