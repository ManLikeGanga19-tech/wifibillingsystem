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
    "apps.loyalty",
    "apps.maps",
    "apps.fibre",
    "apps.fleet",
    "apps.signup",
    "apps.assistant",
    "apps.developer",
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

# Origins allowed to send state-changing requests with our cookies. Cookie auth
# means CSRF is a live threat (a Bearer token never was), so this list is a
# security control, not configuration noise.
CSRF_TRUSTED_ORIGINS = [
    o
    for o in os.environ.get(
        "CSRF_TRUSTED_ORIGINS",
        # dev: the consoles (4600 ISP, 4700 portal, 4800 platform), the marketing
        # site (4900), and the API itself
        "http://localhost:4600,http://localhost:4700,http://localhost:4800,"
        "http://localhost:4900,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]

REST_FRAMEWORK = {
    # Turn a delete-blocked-by-references (ProtectedError) into a clean 409 instead of a 500.
    "EXCEPTION_HANDLER": "apps.core.exceptions.drf_exception_handler",
    # Cookie-first: the browser sends an httpOnly JWT cookie, so the frontends
    # store NOTHING (no localStorage anywhere — see apps/accounts/cookie_auth.py).
    # The header fallback keeps scripts, tests and the CLI working.
    #
    # SessionAuthentication is deliberately ABSENT. We do not use Django sessions
    # for the API, and leaving it in meant any stray sessionid cookie authenticated
    # the request and enforced CSRF — which is exactly what broke the captive
    # portal. CSRF is now enforced by CookieJWTAuthentication itself, only for
    # cookie-authenticated writes, where it actually applies.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.cookie_auth.CookieJWTAuthentication",
        # Developer API tokens (Authorization: Token wos_…). Runs after cookie/Bearer so it only
        # ever sees the `Token` scheme; a token acts as its creator, scoped to their tenant.
        "apps.developer.auth.ApiTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # WITHOUT THESE THE RATES BELOW DO NOTHING. DRF only applies a default throttle if a
    # class is named here; the rates alone are inert configuration that READS like
    # protection. Every endpoint that doesn't declare its own scope was unlimited until
    # this was added (audit F1). Views with an explicit `throttle_classes` still override.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        # Signed-in staff are generous by comparison — a busy console legitimately makes a
        # burst of calls per screen — but still bounded, so a stolen session or a runaway
        # script can't scrape a whole tenant's data at machine speed.
        "user": "600/min",
        # Password guessing. Per-IP, and paired with a per-ACCOUNT lockout in
        # auth_views — an attacker with a botnet walks straight past an IP limit, and
        # an attacker spraying one password across every account walks straight past an
        # account limit. You need both.
        "login": "10/min",
        "stk-push": "10/min",
        "voucher-redeem": "15/min",
        # A technician's device streams location every ~45s; allow bursts on movement but bound it
        # so a runaway client (or a stolen tech session) can't hammer the endpoint.
        "fleet-ping": "20/min",
        # Anonymous, and answers questions about a NAMED customer — the natural place to
        # enumerate an ISP's whole base. Tight, and paired with a phone-digits check.
        "account-lookup": "10/min",
        # Tap-to-approve device management — token-gated, but bounded so a leaked token
        # can't hammer the router.
        "device-mgmt": "40/min",
        # The "text me a link to manage my devices" recovery — sends SMS, so tight.
        "device-recover": "5/min",
        # The 5-step wizard makes several calls per applicant, so the old
        # 5/hour would have blocked a legitimate signup halfway through. The real
        # abuse control is PER-TARGET (SignupThrottle: 3 codes/email/hr,
        # 10/IP/hr) — this is just a coarse backstop.
        "signup": "60/hour",
        "signup-check": "120/hour",  # slug/name availability, typed live
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
    # Many models have a `status` field. The generator names most of them from
    # their model, but two collide and fall back to junk like "Status9e7Enum" — a
    # client generated from the schema would not know which "status" it holds.
    # Name those two explicitly.
    #
    # The values MUST be module-level (see apps/core/enums.py): overrides are
    # resolved with import_string, which splits on the last dot, so a nested
    # `Model.Status.choices` path cannot be imported.
    # NB: an enum name must not collide with a SERIALIZER's component name either —
    # "TransactionStatus" would clash with TransactionStatusSerializer.
    "ENUM_NAME_OVERRIDES": {
        "OperatorStatus": "apps.core.enums.OPERATOR_STATUS_CHOICES",
        "PaymentStatus": "apps.core.enums.TRANSACTION_STATUS_CHOICES",
        # SMS and email share the platform/own choice set — one name, not two.
        "GatewayMode": "apps.core.enums.GATEWAY_MODE_CHOICES",
    },
}

# Fleet tracking (technician location). How long a breadcrumb trail is kept before the nightly
# prune deletes it, and how fresh a ping must be to read as "live" on the dispatch map. Both
# env-overridable so an ISP can tighten retention or widen the live window for sparse rural pings.
FLEET_RETENTION_HOURS = int(os.getenv("FLEET_RETENTION_HOURS", "24"))
FLEET_LIVE_MINUTES = int(os.getenv("FLEET_LIVE_MINUTES", "10"))

# Celery
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TIME_LIMIT = 120
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "sweep-expired-signups": {
        "task": "apps.signup.tasks.sweep_expired_signups",
        "schedule": crontab(minute=15, hour=3),
    },
    # An ISP watching a top-up spinner has already paid. Callbacks get dropped, so chase
    # them fast — this is the same lesson that fixed the hotspot payment bug.
    "reconcile-pending-topups": {
        "task": "apps.billing.tasks.reconcile_pending_topups",
        "schedule": 30.0,
    },
    # Warn before the SMS balance hits zero, not after the receipts have stopped.
    "warn-low-platform-balance": {
        "task": "apps.notifications.tasks.warn_low_platform_balance",
        "schedule": crontab(minute=0),  # hourly; the task itself warns once per fall
    },
    # Tell an ISP they are past due before new sales stop. Restriction/lockout themselves
    # are DERIVED (enforced live on every request), so this task only sends the heads-up.
    "warn-past-due-operators": {
        "task": "apps.billing.tasks.warn_past_due_operators",
        "schedule": crontab(minute=5),  # hourly; warns once per fall
    },
    # Issue each ISP their monthly statement for the prior month. A record, not the
    # enforcement clock — the ladder already ran all month on live exposure.
    "issue-monthly-invoices": {
        "task": "apps.billing.tasks.issue_monthly_invoices",
        "schedule": crontab(minute=45, hour=0, day_of_month=1),
    },
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
    # Fixed-line lifecycle (Settings > PPPoE). All no-op for an ISP on the defaults.
    "prune-dormant-pppoe": {
        "task": "apps.pppoe.tasks.prune_dormant_pppoe_clients",
        "schedule": crontab(minute=45, hour=3),
    },
    "cancel-stale-suspended-pppoe": {
        "task": "apps.pppoe.tasks.cancel_stale_suspended_pppoe_clients",
        "schedule": crontab(minute=50, hour=6),  # after the suspend sweep
    },
    # Fleet tracking: delete technician location pings older than the retention window, so there
    # is never a permanent movement archive. Nightly, off-peak.
    "prune-location-pings": {
        "task": "apps.fleet.tasks.prune_location_pings",
        "schedule": crontab(minute=20, hour=3),
    },
    "remind-pppoe-expiry": {
        "task": "apps.pppoe.tasks.remind_pppoe_expiry",
        "schedule": crontab(minute=15),  # hourly; once per client per cycle
    },
    # Live PPPoE usage metering: delta-poll each router's interface counters, accumulate
    # per cycle, and fire FUP alerts. 5-minute cadence (agreed) — 2 bulk calls per router.
    "poll-pppoe-usage": {
        "task": "apps.pppoe.tasks.poll_pppoe_usage",
        "schedule": 300.0,
    },
    # Cheap online/offline presence sweep, separate from the heavy usage poll above, so a
    # customer who just dialed in lights up "live" within ~a minute instead of up to five.
    # One /ppp/active call per router — safe to run this often.
    "poll-pppoe-presence": {
        "task": "apps.pppoe.tasks.poll_pppoe_presence",
        "schedule": 60.0,
    },
    # Captive-hotspot lifecycle (Settings > Hotspot). Both no-op for an ISP on the defaults.
    "prune-dormant-hotspot": {
        "task": "apps.provisioning.tasks.prune_dormant_hotspot_subscribers",
        "schedule": crontab(minute=50, hour=3),
    },
    "expire-unused-hotspot-vouchers": {
        "task": "apps.provisioning.tasks.expire_unused_hotspot_vouchers",
        "schedule": crontab(minute=55, hour=3),
    },
    "expire-sessions": {
        "task": "apps.provisioning.tasks.expire_sessions",
        "schedule": 60.0,
    },
    # Text customers a few minutes before their WiFi runs out, so they renew instead
    # of silently dropping offline.
    "warn-expiring-sessions": {
        "task": "apps.provisioning.tasks.warn_expiring_sessions",
        "schedule": 60.0,
    },
    # Sync live data usage off the routers (for cap warnings + reporting). The router
    # enforces the cap itself; this is so we know about it too.
    "sync-hotspot-usage": {
        "task": "apps.provisioning.tasks.sync_hotspot_usage",
        "schedule": 120.0,
    },
    # Reconnect paid customers whose provisioning failed while a router was briefly
    # down. Runs often, because a hotspot customer paid seconds ago and is waiting.
    "retry-failed-provisions": {
        "task": "apps.provisioning.tasks.retry_failed_provisions",
        "schedule": 60.0,
    },
    # Every 20s, not every 5 min: this is the safety net that connects a paid customer
    # when the M-Pesa callback is lost, and it has to fire while they are still waiting
    # at the hotspot — not minutes later once the portal has timed out.
    "reconcile-pending-transactions": {
        "task": "apps.payments.tasks.reconcile_pending_transactions",
        "schedule": 20.0,
    },
    # Every 60s (was 300s) so a rebooted router recovers in the console on its own within
    # ~a minute of its tunnel re-forming, instead of sitting "offline" for up to 5. The
    # floor below that is the router's own boot + WireGuard re-dial. Manual "resync" does a
    # live check for instant on-demand recovery.
    "check-router-health": {
        "task": "apps.provisioning.tasks.check_router_health",
        "schedule": 60.0,
    },
    "sync-all-routers-nightly": {
        "task": "apps.provisioning.tasks.sync_all_routers",
        "schedule": crontab(minute=0, hour=3),
    },
    # Daily sales digest to opted-in ISPs (Settings > Operator alerts). Morning, after the
    # prior day has fully closed, so the figure is final.
    "send-sales-digests": {
        "task": "apps.notifications.tasks.send_sales_digests",
        "schedule": crontab(minute=30, hour=6),
    },
}

# Settlement verification auto-activates an ISP (live in minutes, no human in the
# loop) because Safaricom/the bank already ran KYC to issue the account we just
# proved they control. Flip this on to force a human review for flagged signups.
SETTLEMENT_REQUIRES_MANUAL_REVIEW = (
    os.getenv("SETTLEMENT_REQUIRES_MANUAL_REVIEW", "false").lower() == "true"
)

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

# The domain every ISP gets a subdomain of: acme.wifios.co.ke. This is the address a
# customer's phone is sent to by the captive portal, so it is baked into the hotspot
# login page on every router — see provisioning.onboarding and core.domains.
TENANT_BASE_DOMAIN = os.getenv("TENANT_BASE_DOMAIN", "wifios.co.ke")

# --- WireGuard management plane (docs/WIREGUARD_MANAGEMENT_PLANE.md) ---
# Every router dials the hub outbound (CGNAT-proof); the control plane addresses it back at
# its overlay /32. NONE of these are secrets: WireGuard public keys and the hub endpoint are
# public by definition. The only secret — each router's PRIVATE key — is generated per-router
# and stored Fernet-encrypted (never here), honouring the no-secrets-in-code rule.
WG_OVERLAY_CIDR = os.getenv("WG_OVERLAY_CIDR", "10.88.0.0/16")
WG_HUB_IP = os.getenv("WG_HUB_IP", "10.88.0.1")
# host:port the router dials, e.g. hub.wifios.co.ke:51820. Empty until the hub is stood up.
WG_HUB_ENDPOINT = os.getenv("WG_HUB_ENDPOINT", "")
# The hub's WireGuard public key (public by definition), pasted into each router's peer.
WG_HUB_PUBLIC_KEY = os.getenv("WG_HUB_PUBLIC_KEY", "")
# The hub's PRIVATE key — lives ONLY on the hub host / secret manager, never shipped to a
# router. Optional here: the console can render the hub config with a placeholder so the key
# is filled in on the box itself, keeping the secret off this server entirely.
WG_HUB_PRIVATE_KEY = os.getenv("WG_HUB_PRIVATE_KEY", "")
WG_KEEPALIVE_SECONDS = int(os.getenv("WG_KEEPALIVE_SECONDS", "25"))

# Dev/staging escape hatch: when set, routers redirect HERE instead of the tenant's real
# subdomain (which does not resolve from a laptop or an ngrok tunnel). Unset in
# production, where each ISP's portal genuinely lives on their own subdomain.
PORTAL_BASE_URL = os.getenv("PORTAL_BASE_URL", "")

# The operator a captive portal falls back to when NO tenant resolves — no ISP subdomain and
# no ?router= param, e.g. hitting the co-located staging portal at its bare host. Empty in
# PRODUCTION (every ISP has its own subdomain, so this never fires and an unknown host stays
# neutral). Set it on a single-tenant / staging box (e.g. "homelink", our own ISP) so the bare
# portal wears a real brand and shows real plans instead of the neutral WIFI.OS default.
PORTAL_DEFAULT_OPERATOR_SLUG = os.getenv("PORTAL_DEFAULT_OPERATOR_SLUG", "")

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

# AI Assistant (Settings > AI Assistant). The PLATFORM DEFAULT key an ISP falls back on when
# they don't bring their own — env-only, never in code. Blank = the assistant is off until an ISP
# supplies their own key. AI_DEFAULT_PROVIDER picks which platform key the default uses.
AI_DEFAULT_PROVIDER = os.getenv("AI_DEFAULT_PROVIDER", "claude")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

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
