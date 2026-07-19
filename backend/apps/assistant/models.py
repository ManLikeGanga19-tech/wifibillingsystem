"""Settings > AI Assistant — which model powers an ISP's dashboard assistant, and (optionally)
their own API key.

The key is the ISP's OWN credential: if set, the assistant calls their chosen provider on their
account and their bill. Left blank, the ISP rides the platform default (Danamo's key, from the
environment — never in code). Stored Fernet-encrypted and never returned in full after saving.
"""

from django.db import models

from apps.core.fields import EncryptedTextField
from apps.core.models import Operator


class Provider(models.TextChoices):
    CLAUDE = "claude", "Claude (Anthropic)"
    OPENAI = "openai", "OpenAI"


class AISettings(models.Model):
    operator = models.OneToOneField(
        Operator, on_delete=models.CASCADE, related_name="ai_settings"
    )
    provider = models.CharField(
        max_length=10, choices=Provider.choices, default=Provider.CLAUDE
    )
    #: The ISP's OWN provider key. Blank = use the platform default. Encrypted at rest.
    api_key = EncryptedTextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI settings for {self.operator.slug}"
