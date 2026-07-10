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

REST_FRAMEWORK = {**REST_FRAMEWORK}  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "anon": "1000/min",
    "stk-push": "1000/min",
    "voucher-redeem": "1000/min",
    "signup": "1000/min",
}
