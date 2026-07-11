from cryptography.fernet import Fernet

from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["*"]  # tenancy tests exercise arbitrary tenant subdomains

# Ephemeral per-run key: tests exercise encryption without any key living anywhere
FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()

# Run Celery tasks inline so tests exercise the full payment -> provision flow
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Loosen every throttle, whatever it is called. Listing the scopes by hand meant a
# NEW scope blew up the suite with "No default throttle rate set for 'x'" — derive
# them from base instead, so a scope can never be forgotten here.
#
# NB this only relaxes DRF's per-endpoint throttles. The per-TARGET abuse controls
# (SignupThrottle: codes per email / per IP) are ordinary model logic and stay
# fully in force — which is exactly what the abuse tests exercise.
REST_FRAMEWORK = {**REST_FRAMEWORK}  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    scope: "1000/min" for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
}
