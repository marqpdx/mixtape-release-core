from django.core.exceptions import ImproperlyConfigured
from django.db import models

# Values prefixed with this were encrypted client-side (Phase C E2E). The server
# stores and returns them as-is — it cannot and should not apply Fernet on top.
_E2E_PREFIX = "e2e:"


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

    Values prefixed with `e2e:` are client-side E2E ciphertext (Phase C Private/
    Ephemeral conversations). They bypass Fernet on both read and write — the server
    stores the opaque blob and returns it; only the originating client can decrypt.
    """

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        if value.startswith(_E2E_PREFIX):
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
        if value.startswith(_E2E_PREFIX):
            return value
        return _fernet().encrypt(value.encode()).decode()
