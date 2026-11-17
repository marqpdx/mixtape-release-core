"""check_field_encryption and field_encryption_canary: counts and states only,
never a stored value, and only the canary command writes."""

from io import StringIO

from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from sourcework.encryption_canary import CANARY_PLAINTEXT, canary_queryset
from sourcework.models import ExternalConnection

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()
SECRET = "plaintext-that-must-never-be-printed-7f3c"


def _run(name, *args):
    out, err = StringIO(), StringIO()
    try:
        call_command(name, *args, stdout=out, stderr=err)
        code = 0
    except CommandError as exc:
        code = exc.returncode
        err.write(str(exc))
    return code, out.getvalue(), err.getvalue()


def probe(*args):
    return _run("check_field_encryption", *args)


def canary(*args):
    return _run("field_encryption_canary", *args)


def _connection(**kwargs):
    defaults = {"provider": "test", "provider_account_id": "", "credential_payload": SECRET}
    defaults.update(kwargs)
    return ExternalConnection.objects.create(**defaults)


SOURCEWORK = "sourcework_externalconnection.credential_payload"
CHAT = "chat_chatmessage.text"


class CheckFieldEncryptionTests(TestCase):
    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_ok_counts_every_encrypted_column(self):
        _connection()
        _connection()
        code, out, _ = probe()
        self.assertEqual(code, 0)
        self.assertIn("key: well formed", out)
        self.assertIn(f"{SOURCEWORK}: fernet-shaped ok 2, failed 0", out)
        self.assertIn(f"{CHAT}: fernet-shaped ok 0, failed 0", out)
        self.assertIn("canary: absent", out)
        self.assertIn("result: OK", out)

    def test_failed_values_exit_non_zero(self):
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_A):
            _connection()
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_B):
            _connection()
            code, out, _ = probe()
        self.assertEqual(code, 1)
        self.assertIn(f"{SOURCEWORK}: fernet-shaped ok 1, failed 1", out)
        self.assertIn("result: FAILED", out)

    def test_plaintext_and_empty_values_are_not_counted(self):
        # Raw SQL: the ORM (update() too) encrypts even "" on the way in, so
        # legacy plaintext and a truly empty column can only be made directly.
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_A):
            legacy, empty = _connection(), _connection()
            table = ExternalConnection._meta.db_table
            with connection.cursor() as cur:
                for row, value in ((legacy, "legacy plaintext"), (empty, "")):
                    cur.execute(
                        f"UPDATE {table} SET credential_payload = %s WHERE id = %s", [value, row.pk]
                    )
            code, out, _ = probe()
        self.assertEqual(code, 0)
        self.assertIn(f"{SOURCEWORK}: fernet-shaped ok 0, failed 0", out)

    @override_settings(FIELD_ENCRYPTION_KEY="not-a-fernet-key")
    def test_malformed_key(self):
        code, out, err = probe()
        self.assertEqual(code, 1)
        self.assertIn("key: malformed", out)
        self.assertNotIn("not-a-fernet-key", out + err)

    @override_settings(FIELD_ENCRYPTION_KEY=None)
    def test_missing_key(self):
        code, out, _ = probe()
        self.assertEqual(code, 1)
        self.assertIn("key: missing", out)

    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_canary_present_and_opens(self):
        self.assertEqual(canary("--create")[0], 0)
        code, out, _ = probe("--require-canary")
        self.assertEqual(code, 0)
        self.assertIn("canary: present and opens", out)
        self.assertIn(f"{SOURCEWORK}: fernet-shaped ok 1, failed 0", out)

    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_canary_absent_fails_only_when_required(self):
        self.assertEqual(probe()[0], 0)
        code, out, _ = probe("--require-canary")
        self.assertEqual(code, 1)
        self.assertIn("canary: absent", out)

    def test_canary_wrong_key(self):
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_A):
            canary("--create")
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_B):
            code, out, _ = probe()
        self.assertEqual(code, 1)
        self.assertIn("canary: FAILS: does not decrypt with this key", out)

    def test_no_value_or_key_in_output(self):
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_A):
            _connection()
            canary("--create")
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_B):
            _connection()
            _, out_b, err_b = probe()
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_A):
            _, out_a, err_a = probe()
        printed = out_a + err_a + out_b + err_b
        for needle in (SECRET, CANARY_PLAINTEXT, KEY_A, KEY_B, "gAAAAA"):
            self.assertNotIn(needle, printed)

    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_probe_writes_nothing(self):
        _connection()
        before = list(ExternalConnection.objects.values_list("pk", "updated_at"))
        probe("--require-canary")
        self.assertEqual(list(ExternalConnection.objects.values_list("pk", "updated_at")), before)


class FieldEncryptionCanaryTests(TestCase):
    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_create_writes_one_hidden_row_through_the_encrypted_field(self):
        code, out, _ = canary("--create")
        self.assertEqual(code, 0)
        self.assertIn("created 1 row", out)
        row = canary_queryset().get()
        self.assertIsNone(row.group_id)
        self.assertIsNone(row.owner_id)
        self.assertEqual(row.status, "revoked")
        self.assertEqual(row.credential_payload, CANARY_PLAINTEXT)
        self.assertFalse(row.source_grants.exists())

    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_create_twice_writes_once(self):
        canary("--create")
        code, out, _ = canary("--create")
        self.assertEqual(code, 0)
        self.assertIn("nothing written", out)
        self.assertEqual(canary_queryset().count(), 1)

    def test_create_refuses_over_a_failing_canary(self):
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_A):
            canary("--create")
        with override_settings(FIELD_ENCRYPTION_KEY=KEY_B):
            code, _, err = canary("--create")
        self.assertEqual(code, 1)
        self.assertIn("Refusing", err)
        self.assertEqual(canary_queryset().count(), 1)

    @override_settings(FIELD_ENCRYPTION_KEY=None)
    def test_create_without_key_writes_nothing(self):
        code, _, _ = canary("--create")
        self.assertEqual(code, 1)
        self.assertFalse(canary_queryset().exists())

    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_delete_is_the_undo_and_touches_only_the_canary(self):
        other = _connection()
        canary("--create")
        code, out, _ = canary("--delete")
        self.assertEqual(code, 0)
        self.assertIn("deleted 1 row(s)", out)
        self.assertFalse(canary_queryset().exists())
        self.assertTrue(ExternalConnection.objects.filter(pk=other.pk).exists())

    @override_settings(FIELD_ENCRYPTION_KEY=KEY_A)
    def test_no_flag_is_read_only(self):
        code, out, _ = canary()
        self.assertEqual(code, 0)
        self.assertIn("canary: absent", out)
        self.assertFalse(canary_queryset().exists())
