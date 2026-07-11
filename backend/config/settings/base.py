"""Base settings shared by all environments. Environment-specific values come from env vars."""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = False
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.plans",
    "apps.payments",
    "apps.provisioning",
    "apps.vouchers",
    "apps.notifications",
    "apps.ops",
    "apps.billing",
    "apps.pppoe",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.tenancy.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60
    )
}

AUTH_USER_MODEL = "accounts.User"

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

# Auth cookies are shared across the apps + API. In production they all live under
# wifios.co.ke, so scope the cookie to the parent domain; blank in dev (localhost).
SESSION_COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN", "")

REST_FRAMEWORK = {
    # Cookie-first: the browser sends an httpOnly JWT cookie, so the frontends
    # store NOTHING (no localStorage anywhere — see apps/accounts/cookie_auth.py).
    # The header fallback keeps scripts, tests and the CLI working.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.cookie_auth.CookieJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "stk-push": "10/min",
        "voucher-redeem": "15/min",
        "signup": "5/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "WIFI.OS Billing API",
    "DESCRIPTION": "WISP hotspot billing: plans, M-Pesa, provisioning, vouchers, messaging",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TIME_LIMIT = 120
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "charge-monthly-base-fees": {
        "task": "apps.billing.tasks.charge_monthly_base_fees",
        "schedule": crontab(minute=30, hour=0, day_of_month=1),
    },
    "charge-pppoe-user-fees": {
        "task": "apps.billing.tasks.charge_pppoe_user_fees",
        "schedule": crontab(minute=45, hour=0, day_of_month=1),
    },
    "issue-pppoe-invoices": {
        "task": "apps.pppoe.tasks.issue_due_invoices",
        "schedule": crontab(minute=0, hour=6),
    },
    "suspend-overdue-pppoe": {
        "task": "apps.pppoe.tasks.suspend_overdue_clients",
        "schedule": crontab(minute=30, hour=6),
    },
    "expire-sessions": {
        "task": "apps.provisioning.tasks.expire_sessions",
        "schedule": 60.0,
    },
    "reconcile-pending-transactions": {
        "task": "apps.payments.tasks.reconcile_pending_transactions",
        "schedule": 300.0,
    },
    "check-router-health": {
        "task": "apps.provisioning.tasks.check_router_health",
        "schedule": 300.0,
    },
    "sync-all-routers-nightly": {
        "task": "apps.provisioning.tasks.sync_all_routers",
        "schedule": crontab(minute=0, hour=3),
    },
}

# Safaricom Daraja (defaults are the public sandbox values)
DARAJA_BASE_URL = os.getenv("DARAJA_BASE_URL", "https://sandbox.safaricom.co.ke")
DARAJA_CONSUMER_KEY = os.getenv("DARAJA_CONSUMER_KEY", "")
DARAJA_CONSUMER_SECRET = os.getenv("DARAJA_CONSUMER_SECRET", "")
DARAJA_SHORTCODE = os.getenv("DARAJA_SHORTCODE", "")
DARAJA_PASSKEY = os.getenv("DARAJA_PASSKEY", "")
# Public HTTPS base Safaricom can reach, e.g. https://billing.example.com
DARAJA_CALLBACK_BASE_URL = os.getenv("DARAJA_CALLBACK_BASE_URL", "https://example.invalid")
# Shared secret embedded in the callback path so random POSTs 404
DARAJA_CALLBACK_TOKEN = os.getenv("DARAJA_CALLBACK_TOKEN", "dev-callback-token")

# Fernet key for encrypting router/operator secrets at rest. Never in code —
# set via env (.env locally, secret manager in prod). Encryption features raise
# a clear error if it's missing; blank values pass through untouched.
FIELD_ENCRYPTION_KEY = os.getenv("FIELD_ENCRYPTION_KEY", "")

# Africa's Talking SMS
AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
AT_API_KEY = os.getenv("AT_API_KEY", "")
AT_SENDER_ID = os.getenv("AT_SENDER_ID", "")

# WhatsApp Business Cloud API (Meta)
WHATSAPP_API_BASE = os.getenv("WHATSAPP_API_BASE", "https://graph.facebook.com/v20.0")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# Outbound email (console backend in dev; set SMTP env vars in production)
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") == "1"
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "billing@wifios.local")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": os.getenv("DJANGO_LOG_LEVEL", "INFO")},
}
