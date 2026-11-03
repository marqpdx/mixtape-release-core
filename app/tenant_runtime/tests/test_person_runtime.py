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
        with patch("tenant_runtime.api.person_views._on_runtime_worker", return_value=True) as worker:
            resp = self.client.post("/api/me/ai-accounts/claude/disconnect/")
        self.assertEqual(worker.call_args.args[0].name, "tenant_runtime.sign_out_claude_runtime")
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


class RuntimeWorkerTests(TestCase):
    """The CLI runs as a pool user only on the runtime worker: every other worker forbids sudo (ST-3)."""

    def setUp(self):
        self.alice = _user("alice")
        self.client = APIClient()
        with patch.object(pool, "pool_members", return_value=["mxr-1"]), \
                patch.object(pool, "_groups_of", return_value=set()), \
                patch.object(pool, "home_of", return_value="/home/mxr-1"):
            self.rt = ensure_person_runtime(self.alice)

    def test_every_cli_task_routes_to_the_runtime_queue(self):
        from mixtape.celery_app import app

        names = {q.name for q in app.conf.task_queues}
        self.assertIn("runtime", names)
        for task in (
            "tenant_runtime.run_tenant_claude_login",
            "tenant_runtime.run_tenant_codex_login",
            "tenant_runtime.check_ready_claude_runtimes",
            "tenant_runtime.check_claude_runtime",
            "tenant_runtime.sign_out_claude_runtime",
        ):
            self.assertEqual(app.conf.task_routes[task]["queue"], "runtime", task)

    def test_check_asks_the_runtime_worker(self):
        self.client.force_authenticate(self.alice)
        with patch("tenant_runtime.api.person_views._on_runtime_worker", return_value="needs_sign_in") as worker:
            resp = self.client.post("/api/me/ai-accounts/claude/check/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(worker.call_args.args[0].name, "tenant_runtime.check_claude_runtime")
        self.assertEqual(worker.call_args.args[1], str(self.rt.id))

    def test_no_answer_from_the_runtime_worker_is_a_clear_503(self):
        self.client.force_authenticate(self.alice)
        with patch("tenant_runtime.api.person_views._on_runtime_worker", return_value=None):
            resp = self.client.post("/api/me/ai-accounts/claude/check/")
        self.assertEqual(resp.status_code, 503)
        self.assertNotIn("mxr-", resp.content.decode())

    def test_sign_out_task_signs_out_the_runtime_user(self):
        from tenant_runtime.tasks import sign_out_claude_runtime

        with patch("claude.service.logout", return_value=True) as logout:
            self.assertTrue(sign_out_claude_runtime(str(self.rt.id)))
        logout.assert_called_once_with("mxr-1", "/home/mxr-1")


# CLI 2.1.x prints the link inside a terminal hyperlink, then waits for the code (2026-11-03).
_OSC_URL = "https://claude.com/cai/oauth/authorize?code=true&state=abc"
_CLI_LINES = [
    "Opening browser to sign in…\n",
    f"If the browser didn't open, visit: \x1b]8;;{_OSC_URL}\x07{_OSC_URL}\x1b]8;;\x07\n",
]
_CODE = "kFbl6aNOhbTCtestcode#state-abc"


class _FakeLogin:
    """Stands in for `claude auth login`: prints the link, exits 0 once a code arrives on stdin."""

    def __init__(self, on_poll=None, never_exits=False):
        self.stdout = iter(_CLI_LINES)
        self.stdin = MagicMock()
        self.on_poll = on_poll
        self.never_exits = never_exits
        self.polls = 0
        self.returncode = None
        self.killed = False

    def __call__(self, *args, **kwargs):
        return self

    def poll(self):
        self.polls += 1
        if self.on_poll:
            self.on_poll(self.polls)
        if self.stdin.write.called and not self.never_exits:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.killed = True
        self.returncode = -15

    kill = terminate

    def wait(self, timeout=None):
        return self.returncode


class SignInCodeTests(TestCase):
    """The paste-the-code sign-in (ST-3, 2026-11-03)."""

    def setUp(self):
        self.alice = _user("alice")
        self.bob = _user("bob")
        self.client = APIClient()
        with patch.object(pool, "pool_members", return_value=["mxr-1", "mxr-2"]), \
                patch.object(pool, "_groups_of", return_value=set()), \
                patch.object(pool, "home_of", side_effect=lambda n: f"/home/{n}"):
            self.rt = ensure_person_runtime(self.alice)

    def _awaiting(self):
        return self.rt.login_sessions.create(login_url=_OSC_URL, status="awaiting_auth")

    def test_link_is_found_inside_a_terminal_hyperlink(self):
        from tenant_runtime.tasks import _URL_RE, _plain

        self.assertEqual(_URL_RE.search(_plain(_CLI_LINES[1])).group(0), _OSC_URL)

    def test_code_is_held_for_the_waiting_sign_in_and_never_sent_back(self):
        session = self._awaiting()
        self.client.force_authenticate(self.alice)
        resp = self.client.post("/api/me/ai-accounts/claude/login/code/", {"code": _CODE}, format="json")
        self.assertEqual(resp.status_code, 202)
        self.assertNotIn(_CODE, resp.content.decode())
        session.refresh_from_db()
        self.assertEqual(session.pending_code, _CODE)
        self.assertNotIn(_CODE, self.client.get("/api/me/ai-accounts/claude/login/").content.decode())

    def test_a_second_paste_cannot_replace_one_in_flight(self):
        self._awaiting()
        self.client.force_authenticate(self.alice)
        self.client.post("/api/me/ai-accounts/claude/login/code/", {"code": _CODE}, format="json")
        resp = self.client.post("/api/me/ai-accounts/claude/login/code/", {"code": "another-code-123"}, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.rt.login_sessions.get().pending_code, _CODE)

    def test_no_code_without_a_sign_in_showing_its_link(self):
        self.client.force_authenticate(self.alice)
        url = "/api/me/ai-accounts/claude/login/code/"
        self.assertEqual(self.client.post(url, {"code": _CODE}, format="json").status_code, 409)
        self.rt.login_sessions.create()  # starting: no link yet
        self.assertEqual(self.client.post(url, {"code": _CODE}, format="json").status_code, 409)

    def test_one_person_cannot_send_a_code_to_anothers_sign_in(self):
        session = self._awaiting()
        self.client.force_authenticate(self.bob)
        resp = self.client.post("/api/me/ai-accounts/claude/login/code/", {"code": _CODE}, format="json")
        self.assertEqual(resp.status_code, 409)
        session.refresh_from_db()
        self.assertEqual(session.pending_code, "")

    def test_a_code_cannot_carry_a_second_line(self):
        self._awaiting()
        self.client.force_authenticate(self.alice)
        for bad in ("", "short", "abc defghijk", "abcdefgh\nrm -rf", None, 12345678):
            resp = self.client.post("/api/me/ai-accounts/claude/login/code/", {"code": bad}, format="json")
            self.assertEqual(resp.status_code, 400, bad)

    def test_connect_clears_last_times_error(self):
        self.rt.last_verification_error = 'sudo: The "no new privileges" flag is set'
        self.rt.status = TenantClaudeRuntime.STATUS_FAILED
        self.rt.save()
        self.client.force_authenticate(self.alice)
        with patch("tenant_runtime.tasks.run_tenant_claude_login.delay", return_value=MagicMock(id="t")):
            self.client.post("/api/me/ai-accounts/claude/connect/")
        self.rt.refresh_from_db()
        self.assertEqual(self.rt.last_verification_error, "")

    def _run(self, fake):
        from tenant_runtime.tasks import run_tenant_claude_login

        ok = MagicMock(failure=None)
        with patch("subprocess.Popen", fake), \
                patch("tenant_runtime.tasks._LOGIN_POLL_SECONDS", 0), \
                patch("claude.service.run_blocking", return_value=ok):
            run_tenant_claude_login.run(str(self.rt.id))
        self.rt.refresh_from_db()
        return self.rt.login_sessions.get()

    def test_the_task_types_the_pasted_code_into_the_cli_then_signs_in(self):
        def paste(n):
            session = self.rt.login_sessions.first()
            if n == 3 and session and session.login_url:
                type(session).objects.filter(pk=session.pk).update(pending_code=_CODE)

        fake = _FakeLogin(on_poll=paste)
        session = self._run(fake)
        fake.stdin.write.assert_called_once_with(_CODE + "\n")
        self.assertEqual(session.login_url, _OSC_URL)
        self.assertEqual(session.status, "complete")
        self.assertEqual(session.pending_code, "")
        self.assertEqual(self.rt.status, TenantClaudeRuntime.STATUS_READY)

    def test_a_silent_cli_is_ended_at_expiry(self):
        from django.utils import timezone

        from tenant_runtime.models import TenantClaudeLoginSession

        def expire(n):
            if n == 3:
                TenantClaudeLoginSession.objects.filter(runtime=self.rt).update(
                    expires_at=timezone.now() - timezone.timedelta(seconds=1)
                )

        fake = _FakeLogin(on_poll=expire, never_exits=True)
        fake.stdout = iter([])  # prints nothing at all
        with patch.object(TenantClaudeLoginSession, "is_expired", property(
            lambda s: type(s).objects.filter(pk=s.pk, expires_at__lt=timezone.now()).exists()
        )):
            session = self._run(fake)
        self.assertTrue(fake.killed)
        self.assertEqual(session.status, "expired")
        self.assertEqual(self.rt.status, TenantClaudeRuntime.STATUS_FAILED)
