from django.conf import settings
from django.db import models

from .fields import EncryptedTextField


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Operator(TimeStampedModel):
    """The WISP business. Single row today; becomes the tenant when the platform goes SaaS."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    # Per-operator M-Pesa credentials. Blank means "use the env-var defaults" (phase 1).
    mpesa_shortcode = models.CharField(max_length=20, blank=True)
    mpesa_passkey = EncryptedTextField(blank=True)
    daraja_consumer_key = EncryptedTextField(blank=True)
    daraja_consumer_secret = EncryptedTextField(blank=True)

    def __str__(self):
        return self.name


class OperatorOwnedModel(TimeStampedModel):
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True


class AuditLog(models.Model):
    operator = models.ForeignKey(Operator, null=True, blank=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.target_type}#{self.target_id}"
