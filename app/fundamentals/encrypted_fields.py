from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _fernet():
    from django.conf import settings
    from cryptography.fernet import Fernet

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be set in settings.")
    return Fernet(key.encode() if isinstance(key, str) else key)


class EncryptedTextField(models.TextField):
    """
    TextField that encrypts at rest using Fernet (AES-128-CBC + HMAC-SHA256).
    Key source: settings.FIELD_ENCRYPTION_KEY (env var). DB column stays TEXT.
    """

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except Exception:
            # Plaintext row predating encryption — return as-is during migration window.
            return value

    def get_prep_value(self, value):
        if value is None:
            return value
        if not isinstance(value, str):
            value = str(value)
        return _fernet().encrypt(value.encode()).decode()
