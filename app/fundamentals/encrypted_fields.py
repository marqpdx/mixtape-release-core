import logging
import re

from django.core.exceptions import ImproperlyConfigured
from django.db import models

logger = logging.getLogger(__name__)

# Values prefixed with this were encrypted client-side (Phase C E2E). The server
# stores and returns them as-is — it cannot and should not apply Fernet on top.
_E2E_PREFIX = "e2e:"

# Every Fernet token is URL-safe base64 of a version byte 0x80 followed by an
# 8-byte timestamp, so it always begins "gAAAAA". Plaintext written before
# encryption does not look like this; a token that fails to decrypt is a
# wrong, rotated or missing key, never text.
_FERNET_TOKEN = re.compile(r"\AgAAAAA[A-Za-z0-9_\-]+={0,2}\Z")

# Fields that have already warned about legacy plaintext in this process.
_warned_plaintext: set[str] = set()


class EncryptedFieldDecryptError(Exception):
    """A stored Fernet token could not be decrypted with the configured key.

    Raised instead of returning the ciphertext as if it were text. The message
    names the field only; it never carries the stored value.
    """


def _fernet():
    from django.conf import settings
    from cryptography.fernet import Fernet

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be set in settings.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def looks_like_fernet_token(value: str) -> bool:
    return bool(_FERNET_TOKEN.match(value))


class EncryptedTextField(models.TextField):
    """
    TextField that encrypts at rest using Fernet (AES-128-CBC + HMAC-SHA256).
    Key source: settings.FIELD_ENCRYPTION_KEY (env var). DB column stays TEXT.

    Values prefixed with `e2e:` are client-side E2E ciphertext (Phase C Private/
    Ephemeral conversations). They bypass Fernet on both read and write — the server
    stores the opaque blob and returns it; only the originating client can decrypt.

    Reading: a Fernet-shaped value is decrypted, and a failure raises
    EncryptedFieldDecryptError (logged); a missing key raises ImproperlyConfigured.
    Neither ever returns ciphertext as text. Any other value is legacy plaintext
    from before encryption: it is returned as-is, with one warning per field per
    process, until it is re-encrypted.
    """

    def _label(self) -> str:
        model = getattr(self, "model", None)
        if model is None:
            return self.name or "EncryptedTextField"
        return f"{model._meta.label}.{self.name}"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        if value.startswith(_E2E_PREFIX):
            return value
        if not looks_like_fernet_token(value):
            label = self._label()
            if label not in _warned_plaintext:
                _warned_plaintext.add(label)
                logger.warning(
                    "encrypted_field_legacy_plaintext field=%s: a stored value is not "
                    "a Fernet token and is returned as plaintext; re-encrypt this column.",
                    label,
                )
            return value

        from cryptography.fernet import InvalidToken

        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            label = self._label()
            logger.error(
                "encrypted_field_decrypt_failed field=%s: a stored Fernet token did not "
                "decrypt with FIELD_ENCRYPTION_KEY (wrong, rotated or corrupted key).",
                label,
            )
            raise EncryptedFieldDecryptError(
                f"{label}: stored value did not decrypt with the configured key."
            ) from None

    def get_prep_value(self, value):
        if value is None:
            return value
        if not isinstance(value, str):
            value = str(value)
        if value.startswith(_E2E_PREFIX):
            return value
        return _fernet().encrypt(value.encode()).decode()
