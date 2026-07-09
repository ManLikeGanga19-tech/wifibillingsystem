"""Fernet-encrypted model field for secrets (router passwords, Daraja credentials)."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with Fernet.generate_key() "
            "and set it in the environment (.env locally, secret manager in production)."
        )
    return Fernet(key.encode())


class EncryptedTextField(models.TextField):
    description = "Text encrypted at rest with Fernet"

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        return _fernet().encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Value predates encryption (or key rotated); surface as-is rather than crash.
            return value
