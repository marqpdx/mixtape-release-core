"""Person runtimes and the /api/me/ai-accounts/ routes (Service Trust ST-3). Needs the test database."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from tenant_runtime import pool
from tenant_runtime.models import TenantClaudeRuntime
from tenant_runtime.resolve import (
    PERSON_DEFAULT_MODES,
    RuntimeUnavailable,
    ensure_person_runtime,
    person_runtime,
)


def _user(name):
    return get_user_model().objects.create_user(username=name, email=f"{name}@example.com", password="x")


def _patch_pool(members):
    return [
        patch.object(pool, "pool_members", return_value=members),
        patch.object(pool, "_groups_of", return_value={"mixtape-runtimes"}),
        patch.object(pool, "home_of", side_effect=lambda n: f"/home/{n}"),
    ]


class PersonRuntimeTests(TestCase):
    def setUp(self):
        self.alice = _user("alice")
        self.bob = _user("bob")
        self.patches = _patch_pool(["mxr-1", "mxr-2"])
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_ensure_creates_once_with_a_pool_user_and_default_modes(self):
        rt = ensure_person_runtime(self.alice)
        self.assertEqual(rt.linux_user, "mxr-1")
        self.assertEqual(rt.home_dir, "/home/mxr-1")
        self.assertEqual(rt.status, TenantClaudeRuntime.STATUS_LOGIN_REQUIRED)
        self.assertEqual(rt.allowed_ai_modes, PERSON_DEFAULT_MODES)
        self.assertEqual(ensure_person_runtime(self.alice).pk, rt.pk)

    def test_two_people_get_different_users(self):
        a = ensure_person_runtime(self.alice)
        b = ensure_person_runtime(self.bob)
        self.assertNotEqual(a.linux_user, b.linux_user)

    def test_missing_not_ready_and_disallowed_each_stop_with_their_reason(self):
        with self.assertRaises(RuntimeUnavailable) as missing:
            person_runtime(self.alice, "shuttle_weave_interpret")
        self.assertEqual(missing.exception.code, "runtime_missing")

        rt = ensure_person_runtime(self.alice)
        with self.assertRaises(RuntimeUnavailable) as not_ready:
            person_runtime(self.alice, "shuttle_weave_interpret")
        self.assertEqual(not_ready.exception.code, "runtime_not_ready")

        rt.status = TenantClaudeRuntime.STATUS_READY
        rt.save()
        with self.assertRaises(RuntimeUnavailable) as mode:
            person_runtime(self.alice, "something_else")
        self.assertEqual(mode.exception.code, "mode_not_allowed")
        self.assertEqual(person_runtime(self.alice, "shuttle_weave_interpret").pk, rt.pk)

    def test_a_group_runtime_is_never_a_persons(self):
        from groups.models import Group

        # A Group runtime, even one keyed to the same id as the person, never resolves for them.
        TenantClaudeRuntime.objects.create(
            tenant_content_type=ContentType.objects.get_for_model(Group), tenant_object_id=self.alice.pk,
            linux_user="grp-user", home_dir="/home/grp-user", status=TenantClaudeRuntime.STATUS_READY,
            allowed_ai_modes=list(PERSON_DEFAULT_MODES),
        )
        with self.assertRaises(RuntimeUnavailable):
            person_runtime(self.alice, "shuttle_weave_interpret")


class PersonApiTests(TestCase):
    def setUp(self):
        self.alice = _user("alice")
        self.bob = _user("bob")
        self.client = APIClient()
        self.patches = _patch_pool(["mxr-1", "mxr-2"])
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_requires_sign_in(self):
        self.assertEqual(self.client.get("/api/me/ai-accounts/").status_code, 401)

    def test_state_none_then_connecting(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.get("/api/me/ai-accounts/").json()["claude"]["state"], "none")
        with patch("tenant_runtime.tasks.run_tenant_claude_login.delay", return_value=MagicMock(id="t")) as delay:
            resp = self.client.post("/api/me/ai-accounts/claude/connect/")
        self.assertEqual(resp.status_code, 202)
        runtime = TenantClaudeRuntime.objects.get()
        delay.assert_called_once_with(str(runtime.id))

    def test_response_never_names_the_linux_user(self):
        self.client.force_authenticate(self.alice)
        ensure_person_runtime(self.alice)
        body = self.client.get("/api/me/ai-accounts/").content.decode()
        self.assertNotIn("mxr-", body)
        self.assertNotIn("/home/", body)

    def test_one_person_cannot_see_anothers_sign_in(self):
        rt = ensure_person_runtime(self.alice)
        rt.login_sessions.create(login_url="https://claude.ai/oauth/alice-only")
        self.client.force_authenticate(self.bob)
        body = self.client.get("/api/me/ai-accounts/claude/login/").content.decode()
        self.assertNotIn("alice-only", body)

    def test_empty_pool_is_a_clear_503(self):
        self.client.force_authenticate(self.alice)
        with patch.object(pool, "pool_members", return_value=[]):
            resp = self.client.post("/api/me/ai-accounts/claude/connect/")
        self.assertEqual(resp.status_code, 503)

    def test_disconnect_stops_use_before_signing_out(self):
        rt = ensure_person_runtime(self.alice)
        rt.status = TenantClaudeRuntime.STATUS_READY
        rt.save()
        self.client.force_authenticate(self.alice)
        with patch("claude.service.logout", return_value=True):
            resp = self.client.post("/api/me/ai-accounts/claude/disconnect/")
        self.assertEqual(resp.json()["state"], "needs_sign_in")
        rt.refresh_from_db()
        self.assertEqual(rt.status, TenantClaudeRuntime.STATUS_LOGIN_REQUIRED)


class VerifyTests(TestCase):
    def setUp(self):
        self.alice = _user("alice")
        with patch.object(pool, "pool_members", return_value=["mxr-1"]), \
                patch.object(pool, "_groups_of", return_value=set()), \
                patch.object(pool, "home_of", return_value="/home/mxr-1"):
            self.rt = ensure_person_runtime(self.alice)

    def test_check_never_grants_ready(self):
        from tenant_runtime.tasks import verify_claude_runtime

        with patch("claude.service.auth_status", return_value={"loggedIn": True}):
            self.assertEqual(verify_claude_runtime(self.rt), "unknown")
        self.rt.refresh_from_db()
        self.assertEqual(self.rt.status, TenantClaudeRuntime.STATUS_LOGIN_REQUIRED)

    def test_signed_out_takes_ready_away(self):
        from tenant_runtime.tasks import verify_claude_runtime

        self.rt.status = TenantClaudeRuntime.STATUS_READY
        self.rt.save()
        with patch("claude.service.auth_status", return_value={"loggedIn": False}):
            self.assertEqual(verify_claude_runtime(self.rt), "needs_sign_in")
        self.rt.refresh_from_db()
        self.assertEqual(self.rt.status, TenantClaudeRuntime.STATUS_LOGIN_REQUIRED)
