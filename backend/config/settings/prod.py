import os

from .base import *  # noqa: F403

DEBUG = False

_required = ["DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEY", "DATABASE_URL", "DJANGO_ALLOWED_HOSTS"]
_missing = [v for v in _required if not os.getenv(v)]
if _missing:
    raise RuntimeError(f"Missing required production env vars: {', '.join(_missing)}")

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True

STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}
