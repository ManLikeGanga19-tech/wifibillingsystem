"""Cookie-based JWT auth. NO BROWSER STORAGE ANYWHERE.

Why this exists (a hard rule for this system):

The frontends must never persist auth or app state in localStorage. Anything the
browser holds on to across deploys eventually goes stale, and then a customer has
to "clear their cache" to use the product — which is not an acceptable thing to
ask an ISP, let alone their subscribers. It also bit us directly: a stale
`act_as` slug left in localStorage wedged the whole ISP console with 403s.

So: the server owns the session.
  - Tokens live in **httpOnly** cookies. JavaScript cannot read them (so XSS
    cannot steal them), the browser attaches them automatically, and there is
    nothing for a user to clear.
  - The acting tenant ("view as") is a server-set cookie tied to a live
    ImpersonationGrant — not client state that can drift out of sync.
  - Cookies expire on their own. Stale state cannot survive a deploy.

Bearer tokens still work (`Authorization: Bearer …`) so scripts, tests and the
CLI keep functioning; the cookie is simply checked first for browsers.
"""

from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware as CSRFCheck
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS
from rest_framework_simplejwt.authentication import JWTAuthentication

ACCESS_COOKIE = "wifios_access"
REFRESH_COOKIE = "wifios_refresh"
ACT_AS_COOKIE = "wifios_act_as"


def _cookie_kwargs(max_age: int) -> dict:
    """Same-site by default: in dev the Vite proxy makes the API same-origin, and
    in production the apps and API share the wifios.co.ke parent domain."""
    return {
        "max_age": max_age,
        "httponly": True,
        "secure": not settings.DEBUG,  # HTTPS-only off localhost
        "samesite": "Lax",
        "path": "/",
        **({"domain": settings.SESSION_COOKIE_DOMAIN} if settings.SESSION_COOKIE_DOMAIN else {}),
    }


def set_auth_cookies(response, access: str, refresh: str | None = None):
    access_age = int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    response.set_cookie(ACCESS_COOKIE, access, **_cookie_kwargs(access_age))
    if refresh:
        refresh_age = int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
        response.set_cookie(REFRESH_COOKIE, refresh, **_cookie_kwargs(refresh_age))
    return response


def clear_auth_cookies(response):
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, ACT_AS_COOKIE):
        response.delete_cookie(
            name, path="/", domain=settings.SESSION_COOKIE_DOMAIN or None
        )
    return response


def set_act_as_cookie(response, slug: str):
    """Which ISP a platform user is currently acting for. Readable by JS is fine
    (it is not a credential) — but it is SERVER-SET, so it can never disagree
    with the grant that authorises it."""
    kwargs = _cookie_kwargs(int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()))
    kwargs["httponly"] = False  # the UI shows "you are inside X" from this
    response.set_cookie(ACT_AS_COOKIE, slug, **kwargs)
    return response


def clear_act_as_cookie(response):
    response.delete_cookie(
        ACT_AS_COOKIE, path="/", domain=settings.SESSION_COOKIE_DOMAIN or None
    )
    return response


class CookieJWTAuthentication(JWTAuthentication):
    """Read the JWT from the httpOnly cookie, falling back to the Authorization
    header so non-browser clients (tests, scripts, the CLI) are unaffected.

    CSRF: moving the token from a header into a cookie REINTRODUCES CSRF. A Bearer
    token is immune by construction (an attacker's site cannot set our header), but
    a cookie is attached by the browser automatically — so a malicious page could
    fire a state-changing request as the logged-in user.

    Defence in depth:
      1. `SameSite=Lax` on the cookie (set above) — the browser will not send it on
         a cross-site POST at all. This alone stops classic CSRF.
      2. This double-submit check — an unsafe request authenticated BY COOKIE must
         also echo the CSRF token in `X-CSRFToken`. An attacker cannot read our
         cookie (same-origin policy), so they cannot forge the header.

    Bearer-authenticated requests skip check 2: they were never vulnerable, and
    scripts/tests must keep working.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            return super().authenticate(request)  # Bearer: CSRF-immune by design

        raw = request.COOKIES.get(ACCESS_COOKIE)
        if not raw:
            return None
        validated = self.get_validated_token(raw)
        user = self.get_user(validated)
        self.enforce_csrf(request)  # cookie-authenticated => must prove same-origin
        return user, validated

    def enforce_csrf(self, request):
        """Django's own CSRF machinery, run by hand — DRF views are csrf_exempt at
        the middleware level, so nothing else would check this."""
        if request.method in SAFE_METHODS:
            return

        def reject(reason):
            raise PermissionDenied(f"CSRF Failed: {reason}")

        check = CSRFCheck(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            reject(reason)
