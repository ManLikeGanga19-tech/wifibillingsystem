"""OpenAPI description of our custom auth.

drf-spectacular can only document authenticators it recognises. `CookieJWTAuthentication`
is ours, so we must tell it what the scheme actually is — otherwise every view using
it emits "could not resolve authenticator" and the generated schema silently claims
the API is unauthenticated, which is a lie a client would act on.

One authenticator, two ways in, so we return both definitions:
  - the httpOnly cookie the browsers use (no token is ever stored client-side)
  - the Bearer token scripts/tests/CLI use (CSRF-immune by construction)
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension

from .cookie_auth import ACCESS_COOKIE


class CookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.cookie_auth.CookieJWTAuthentication"
    name = ["cookieAuth", "bearerAuth"]

    def get_security_definition(self, auto_schema):
        return [
            {
                "type": "apiKey",
                "in": "cookie",
                "name": ACCESS_COOKIE,
                "description": (
                    "httpOnly JWT cookie set by `POST /auth/login/`. The browser sends "
                    "it automatically and the frontend stores nothing. Unsafe methods "
                    "must also echo the CSRF token in `X-CSRFToken` (double-submit)."
                ),
            },
            {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": (
                    "For non-browser clients (scripts, CI, CLI). Obtain via "
                    "`POST /auth/token/`. Exempt from CSRF — a header cannot be forged "
                    "cross-origin."
                ),
            },
        ]
