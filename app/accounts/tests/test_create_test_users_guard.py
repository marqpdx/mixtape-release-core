"""
create_test_users refuses to run outside development.

The command creates a superuser (`admin`) with a fixed, public password, and
resets that password if an `admin` user already exists. Run by mistake against
production, it would hand anyone who reads the repo a superuser login. It now
refuses unless DEBUG is true or `--allow-nonlocal` is passed.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

User = get_user_model()


class CreateTestUsersGuardTests(TestCase):
    def _run(self, *args):
        call_command("create_test_users", *args, stdout=StringIO())

    @override_settings(DEBUG=False)
    def test_refuses_when_debug_is_false(self):
        with self.assertRaises(CommandError):
            self._run()
        self.assertFalse(User.objects.filter(username="admin").exists())

    @override_settings(DEBUG=False)
    def test_refusal_leaves_an_existing_admin_password_alone(self):
        User.objects.create_user(username="admin", email="a@example.com", password="original-pass")
        with self.assertRaises(CommandError):
            self._run()
        self.assertTrue(User.objects.get(username="admin").check_password("original-pass"))

    @override_settings(DEBUG=True)
    def test_runs_when_debug_is_true(self):
        self._run()
        self.assertTrue(User.objects.get(username="admin").is_superuser)

    @override_settings(DEBUG=False)
    def test_runs_outside_debug_with_allow_nonlocal(self):
        self._run("--allow-nonlocal")
        self.assertTrue(User.objects.get(username="admin").is_superuser)
