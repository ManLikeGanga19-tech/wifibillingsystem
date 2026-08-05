"""The production settings must let the HEALTH CHECKS through.

This exists because getting it wrong takes the whole site down, and does it silently:
Docker's healthcheck dials localhost:8000 and Caddy's active health check dials the compose
service name (api:8000). If Django answers those with 400 DisallowedHost — or 301-redirects
them to https:// because SECURE_SSL_REDIRECT is on — the container is marked unhealthy and
Caddy stops routing to an API that is perfectly fine. Both happened.

These assert the invariants against the REAL production settings module, so a future edit to
ALLOWED_HOSTS or the SSL-redirect config fails here instead of in a deploy.
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
