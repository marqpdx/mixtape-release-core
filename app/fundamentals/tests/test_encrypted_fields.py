"""EncryptedTextField read/write behaviour. Database-free: the field's own
from_db_value / get_prep_value are exercised directly with throwaway keys."""
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from fundamentals import encrypted_fields
from fundamentals.encrypted_fields import (
    EncryptedFieldDecryptError,
    EncryptedTextField,
    looks_like_fernet_token,
)

KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()


def _field():
    field = EncryptedTextField()
    field.set_attributes_from_name("text")
    return field


def _read(field, stored):
    return field.from_db_value(stored, None, None)


@override_settings(FIELD_ENCRYPTION_KEY=KEY)
class EncryptedTextFieldTests(SimpleTestCase):
    def setUp(self):
        encrypted_fields._warned_plaintext.clear()
        self.field = _field()

    def test_right_key_round_trips(self):
        stored = self.field.get_prep_value("a private message")
        self.assertTrue(looks_like_fernet_token(stored))
        self.assertNotIn("private", stored)
        self.assertEqual(_read(self.field, stored), "a private message")

    def test_empty_string_round_trips(self):
        stored = self.field.get_prep_value("")
        self.assertTrue(looks_like_fernet_token(stored))
        self.assertEqual(_read(self.field, stored), "")

    def test_wrong_key_never_returns_ciphertext(self):
        stored = Fernet(OTHER_KEY.encode()).encrypt(b"written under another key").decode()
        with self.assertLogs("fundamentals.encrypted_fields", level="ERROR") as logs:
            with self.assertRaises(EncryptedFieldDecryptError) as caught:
                _read(self.field, stored)
        self.assertNotIn(stored, str(caught.exception))
        self.assertNotIn(stored, "\n".join(logs.output))
        self.assertIn("encrypted_field_decrypt_failed", "\n".join(logs.output))

    def test_corrupted_token_raises(self):
        stored = self.field.get_prep_value("hello")
        tampered = stored[:-6] + ("A" if stored[-6] != "A" else "B") + stored[-5:]
        with self.assertLogs("fundamentals.encrypted_fields", level="ERROR"):
            with self.assertRaises(EncryptedFieldDecryptError):
                _read(self.field, tampered)

    @override_settings(FIELD_ENCRYPTION_KEY=None)
    def test_missing_key_on_read_raises_not_ciphertext(self):
        stored = Fernet(KEY.encode()).encrypt(b"hello").decode()
        with self.assertRaises(ImproperlyConfigured):
            _read(self.field, stored)

    def test_legacy_plaintext_returned_with_one_warning(self):
        with self.assertLogs("fundamentals.encrypted_fields", level="WARNING") as logs:
            self.assertEqual(_read(self.field, "written before encryption"), "written before encryption")
            self.assertEqual(_read(self.field, "another old row"), "another old row")
        self.assertEqual(len(logs.output), 1)
        self.assertIn("encrypted_field_legacy_plaintext", logs.output[0])
        self.assertNotIn("written before encryption", logs.output[0])

    def test_legacy_empty_string_is_plaintext(self):
        with self.assertLogs("fundamentals.encrypted_fields", level="WARNING"):
            self.assertEqual(_read(self.field, ""), "")

    def test_e2e_values_pass_through_both_ways(self):
        blob = "e2e:opaque-client-ciphertext"
        self.assertEqual(self.field.get_prep_value(blob), blob)
        self.assertEqual(_read(self.field, blob), blob)

    def test_none_passes_through_both_ways(self):
        self.assertIsNone(self.field.get_prep_value(None))
        self.assertIsNone(_read(self.field, None))

    def test_token_shape(self):
        self.assertTrue(looks_like_fernet_token(Fernet(KEY.encode()).encrypt(b"x").decode()))
        for value in ("", "hello", "gAAAA", "gAAAAA with spaces", "e2e:gAAAAAabc"):
            self.assertFalse(looks_like_fernet_token(value), value)
