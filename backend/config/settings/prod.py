"""Production and staging.

Everything here is either "fail loudly if it is not configured" or "close a door that
development leaves open". If you are ever tempted to add a fallback so it boots without
a secret — don't. A process that starts with a missing FIELD_ENCRYPTION_KEY is a process
quietly storing router passwords in plaintext.
"""

import os

from .base import *  # noqa: F403

DEBUG = False

# ---- the secrets, and refusing to run without them ---------------------------------
#
# No defaults, no "change-me" fallback: the process does not start. A misconfigured
# deploy should be a crash you notice in thirty seconds, not a silent downgrade you
# discover in an incident review.
_required = [
    "DJANGO_SECRET_KEY",
    "FIELD_ENCRYPTION_KEY",
    "DATABASE_URL",
    "DJANGO_ALLOWED_HOSTS",
    "DARAJA_CALLBACK_TOKEN",  # the shared secret on the M-Pesa callback URL
]
_missing = [v for v in _required if not os.getenv(v)]
if _missing:
    raise RuntimeError(f"Missing required production env vars: {', '.join(_missing)}")

# ---- transport ---------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
# Caddy terminates TLS and forwards over the private network. Without this, Django
# believes every request is plain http:// and redirect-loops forever.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_HSTS_SECONDS = 63072000  # two years
SECURE_HSTS_INCLUDE_SUBDOMAINS = True  # every ISP subdomain too
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# ---- cookies -----------------------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True

# The CSRF cookie must stay READABLE. That is the double-submit pattern: the client
# echoes it in a header, and an attacker's origin cannot read our cookie to forge one.
# Making it httpOnly would break every write in the console and buy nothing.
CSRF_COOKIE_HTTPONLY = False

# Lax, not None. The API is same-origin with every console (Caddy serves /api on each
# subdomain), so we never need a cross-site cookie — and SameSite=None would hand CSRF a
# much bigger surface in exchange for nothing.
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Scoped to the parent domain, so one login works across acme.wifios.co.ke and
# admin.wifios.co.ke. Safe because a tenant user is pinned to their own operator no
# matter which Host they arrive on (core.tenancy.acting_tenant), and platform staff need
# a live, audited grant to reach a foreign tenant.
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", ".wifios.co.ke")
SESSION_COOKIE_DOMAIN = COOKIE_DOMAIN
CSRF_COOKIE_DOMAIN = COOKIE_DOMAIN

# ---- database ----------------------------------------------------------------------
# Reuse connections rather than a fresh TCP + auth handshake on every request. On one
# box this is most of the difference between a snappy console and a sluggish one.
DATABASES["default"]["CONN_MAX_AGE"] = 60  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# ---- static ------------------------------------------------------------------------
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}

# ---- logging -----------------------------------------------------------------------
# On stdout, because that is where Docker (and any log shipper you add later) reads.
# The money and identity paths are named explicitly: when a payout goes wrong, that line
# has to be findable without grepping past a hundred thousand health checks.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(levelname)s %(asctime)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # The ones you will actually be reading during an incident.
        "apps.billing": {"level": "INFO", "propagate": True},
        "apps.payments": {"level": "INFO", "propagate": True},
        "apps.core.settlement": {"level": "INFO", "propagate": True},
        "apps.accounts.mfa": {"level": "INFO", "propagate": True},
        # Suspicious-request logging: Host header tampering, CSRF failures, and the
        # noise a scanner makes on its way past.
        "django.security": {"level": "WARNING", "propagate": True},
        "django.request": {"level": "WARNING", "propagate": True},
    },
}
