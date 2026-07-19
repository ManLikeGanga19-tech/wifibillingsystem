"""Developer settings: API tokens (programmatic REST access) and outbound webhooks.

API tokens are stored ONLY as a SHA-256 hash — we can verify one but never reproduce it, so a
leaked database still can't hand an attacker a working token. The plaintext is shown exactly once,
at creation. A token acts as the tenant that created it (scoped to that operator's data) and is
revocable at any time.

Webhook signing secrets are the ISP's own credential (they need it to verify our signatures), so
they are Fernet-encrypted at rest and returned to the owner — never a one-way hash.
"""

import hashlib
import secrets

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import Operator

TOKEN_PREFIX = "wos_"
SECRET_PREFIX = "whsec_"


def generate_token() -> tuple[str, str, str]:
    """Return (plaintext, sha256_hash, display_prefix) for a fresh API token."""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_token(plaintext), plaintext[:12]


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(24)


class ApiToken(models.Model):
    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="api_tokens"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    name = models.CharField(max_length=80)
    #: First 12 chars (wos_ + 8) — enough to recognise a token in a list, useless as a credential.
    prefix = models.CharField(max_length=16)
    #: SHA-256 of the plaintext. Unique so a lookup is a single indexed hit.
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)

    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…) for {self.operator.slug}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class Webhook(models.Model):
    operator = models.ForeignKey(
        Operator, on_delete=models.CASCADE, related_name="webhooks"
    )
    label = models.CharField(max_length=80)
    url = models.URLField(max_length=500)
    #: Signs every payload (HMAC-SHA256). The ISP's own credential — encrypted, not hashed.
    secret = EncryptedTextField(default=generate_secret)
    #: Subscribed event keys — a subset of developer.events.EVENT_KEYS.
    events = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    # Last delivery result, so the console can show a health signal without a full delivery log.
    last_delivered_at = models.DateTimeField(null=True, blank=True)
    last_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} -> {self.url}"
