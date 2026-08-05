"""Deploy-critical invariants, asserted against the REAL production settings module.

WHY THIS FILE EXISTS. The test settings deliberately loosen production — ALLOWED_HOSTS is
["*"], SSL redirect is off, throttles are relaxed — so a whole class of bug is INVISIBLE to
the rest of the suite and can only appear during a deploy. That is not hypothetical: the
health check shipped green and then took the staging API down, because Django answered the
probes with 400 DisallowedHost and 301-redirected them to https:// on a plain-HTTP port.

So anything whose failure mode is "only breaks in production" gets pinned here, by importing
config.settings.prod itself rather than trusting the ambient test config. If you add a
setting that behaves differently in prod, add its invariant here too.
"""

import base64
import importlib
import os
from unittest import mock

import pytest

# prod.py refuses to import without these, so the test has to supply them. They are BUILT,
# not written as literals: a random-looking constant in source is exactly what the secret
# scanner is there to catch, and "it's only a test value" is the excuse behind every real
# leaked key. Low-entropy and obviously fake — they only need to be present and well-formed.
_FAKE_SECRET_KEY = "not-a-real-secret-key-for-tests-" + ("a" * 24)
_FAKE_FERNET_KEY = base64.urlsafe_b64encode(b"0" * 32).decode()

PROD_ENV = {
    "DJANGO_SECRET_KEY": _FAKE_SECRET_KEY,
    "FIELD_ENCRYPTION_KEY": _FAKE_FERNET_KEY,
    "DATABASE_URL": "postgres://user:pass@localhost:5432/db",
    "DJANGO_ALLOWED_HOSTS": "wifios.co.ke,admin.wifios.co.ke",
    "DARAJA_CALLBACK_TOKEN": "ci-only",
}


@pytest.fixture
def prod_settings():
    with mock.patch.dict(os.environ, PROD_ENV, clear=False):
        yield importlib.reload(importlib.import_module("config.settings.prod"))


#: What the two health checkers actually send as the Host header.
HEALTH_CHECK_HOSTS = ["localhost", "127.0.0.1", "api"]


@pytest.mark.parametrize("host", HEALTH_CHECK_HOSTS)
def test_the_health_check_hosts_are_allowed(prod_settings, host):
    assert host in prod_settings.ALLOWED_HOSTS


def test_the_configured_public_hosts_are_still_allowed(prod_settings):
    # Adding the internal names must not drop what the environment configured.
    assert "wifios.co.ke" in prod_settings.ALLOWED_HOSTS
    assert "admin.wifios.co.ke" in prod_settings.ALLOWED_HOSTS


def test_arbitrary_hosts_are_still_rejected(prod_settings):
    # The internal names are a health-check allowance, NOT an open Host header.
    assert "evil.example.com" not in prod_settings.ALLOWED_HOSTS
    assert "*" not in prod_settings.ALLOWED_HOSTS


def test_the_health_path_is_exempt_from_the_https_redirect(prod_settings):
    """The probes speak plain HTTP inside the docker network and set no X-Forwarded-Proto,
    so without this they get a 301 to an https:// URL on the plain-HTTP port — which every
    health checker reads as unhealthy."""
    import re

    assert prod_settings.SECURE_SSL_REDIRECT is True  # still on for real traffic
    assert any(
        re.compile(pattern).match("api/v1/health/")
        for pattern in prod_settings.SECURE_REDIRECT_EXEMPT
    )


def test_only_the_health_path_is_exempt(prod_settings):
    import re

    for path in ("api/v1/auth/login/", "api/v1/billing/payouts/", "admin/"):
        assert not any(
            re.compile(pattern).match(path)
            for pattern in prod_settings.SECURE_REDIRECT_EXEMPT
        ), f"{path} must still be forced to https"


# --- throttling (audit F1) ---------------------------------------------------------------


def test_default_throttle_classes_are_configured(prod_settings):
    """Rates alone do NOTHING. Without a default throttle class DRF applies no limit at all,
    so every endpoint that doesn't declare its own scope is unlimited — while the config
    reads like protection. That was the state of production until the audit."""
    classes = prod_settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_CLASSES") or []
    assert any("AnonRateThrottle" in c for c in classes)
    assert any("UserRateThrottle" in c for c in classes)


def test_every_default_throttle_class_has_a_rate(prod_settings):
    """A named throttle class with no matching rate raises at REQUEST time ("No default
    throttle rate set for 'x'") — a 500 in production, not a startup error."""
    rates = prod_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    classes = prod_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]
    for path in classes:
        scope = "anon" if "Anon" in path else "user"
        assert rates.get(scope), f"{path} has no '{scope}' rate"


def test_the_anonymous_account_lookup_is_rate_limited(prod_settings):
    """It answers questions about a NAMED customer without authentication, so it is the
    natural place to enumerate an ISP's base. Tight limit, deliberately."""
    assert prod_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].get("account-lookup")


# --- cookies + transport ------------------------------------------------------------------


def test_cookies_are_secure_in_production(prod_settings):
    assert prod_settings.SESSION_COOKIE_SECURE is True
    assert prod_settings.CSRF_COOKIE_SECURE is True
    assert prod_settings.SESSION_COOKIE_HTTPONLY is True


def test_the_csrf_cookie_stays_readable(prod_settings):
    """Double-submit REQUIRES the client to read this cookie and echo it in a header. Making
    it httpOnly would break every write in the console and buy nothing — an attacker's origin
    still cannot read it."""
    assert prod_settings.CSRF_COOKIE_HTTPONLY is False


def test_cookies_are_samesite_lax_not_none(prod_settings):
    """The API is same-origin with every console, so a cross-site cookie is never needed;
    SameSite=None would widen the CSRF surface in exchange for nothing."""
    assert prod_settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert prod_settings.CSRF_COOKIE_SAMESITE == "Lax"


def test_hsts_covers_every_isp_subdomain(prod_settings):
    """Each ISP is a subdomain, so includeSubDomains is what actually protects tenants."""
    assert prod_settings.SECURE_HSTS_SECONDS >= 31536000
    assert prod_settings.SECURE_HSTS_INCLUDE_SUBDOMAINS is True


def test_proxy_ssl_header_is_set(prod_settings):
    """Caddy terminates TLS and forwards plain HTTP. Without this Django believes every
    request is insecure and redirect-loops forever."""
    assert prod_settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")


def test_debug_is_off(prod_settings):
    assert prod_settings.DEBUG is False


@pytest.mark.parametrize(
    "missing",
    ["DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEY", "DATABASE_URL", "DARAJA_CALLBACK_TOKEN"],
)
def test_production_refuses_to_boot_without_a_required_secret(missing):
    """No defaults, no "change-me" fallback: the process must not start. A container that
    boots with a missing FIELD_ENCRYPTION_KEY is a container quietly storing router
    passwords in plaintext — a crash you notice in thirty seconds is far cheaper."""
    env = {**PROD_ENV}
    env.pop(missing)
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match=missing):
            importlib.reload(importlib.import_module("config.settings.prod"))
