"""Callers on the person's own runtime, on the runtime worker (Service Trust ST-3, step 6, Part A)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import SimpleTestCase, TestCase

from tenant_runtime import pool
from tenant_runtime.models import TenantClaudeRuntime
from tenant_runtime.resolve import PERSON_DEFAULT_MODES, ensure_person_runtime
from tenant_runtime.runtime_queue import forward_to_runtime


def _task(routing_key, *, task_id="t-1", eager=False):
    task = MagicMock()
    task.request = SimpleNamespace(id=task_id, is_eager=eager, delivery_info={"routing_key": routing_key})
    return task


class ForwardToRuntimeTests(SimpleTestCase):
    def test_a_task_on_another_worker_moves_to_the_runtime_worker(self):
        task = _task("catalyst")
        self.assertTrue(forward_to_runtime(task, kwargs={"action_run_id": "a"}))
        task.apply_async.assert_called_once_with(
            args=None, kwargs={"action_run_id": "a"}, queue="runtime", routing_key="runtime")

    def test_on_the_runtime_worker_it_runs_in_place(self):
        task = _task("runtime")
        self.assertFalse(forward_to_runtime(task, kwargs={}))
        task.apply_async.assert_not_called()

    def test_called_directly_or_eagerly_it_runs_in_place(self):
        for task in (_task("catalyst", task_id=None), _task("catalyst", eager=True)):
            self.assertFalse(forward_to_runtime(task, kwargs={}))
            task.apply_async.assert_not_called()


class RoutesTests(SimpleTestCase):
    def test_catalyst_parsing_routes_to_the_runtime_queue(self):
        from mixtape.celery_app import app

        for name in ("catalyst.tasks.run_file_semantic_analysis", "catalyst.tasks.materialize_register_entities"):
            self.assertEqual(app.conf.task_routes[name]["queue"], "runtime", name)

    def test_switchboard_sent_tasks_forward_themselves(self):
        from shuttle.interpretation.tasks import run_cloud_interpretation
        from writing.tasks import generate_linkedin_copy_with_claude_code

        # Bound, so each can read its own delivery info and move itself.
        for task in (run_cloud_interpretation, generate_linkedin_copy_with_claude_code):
            self.assertTrue(task.bind, task.name)

    def test_linkedin_sent_to_catalyst_moves_and_runs_nothing_there(self):
        from writing.tasks import generate_linkedin_copy_with_claude_code as task

        with patch("tenant_runtime.runtime_queue.forward_to_runtime", return_value=True), \
                patch("writing.linkedin_copy_service.generate_linkedin_copy") as generate:
            result = task.run(
                action_run_id="a", tenant_id="t", tenant_namespace="n", principal_user_id=None,
                principal_service_token_id=None, request_payload={}, synopsis_payload={},
            )
        self.assertEqual(result["status"], "forwarded")
        generate.assert_not_called()

    def test_new_person_runtimes_include_catalyst(self):
        self.assertIn("catalyst.parse", PERSON_DEFAULT_MODES)


class CatalystPreflightTests(TestCase):
    """Catalyst runs on the account of the person who started the work, never a Group's (S3)."""

    def setUp(self):
        self.person = get_user_model().objects.create_user(username="cook", email="cook@example.com", password="x")
        with patch.object(pool, "pool_members", return_value=["mxr-1"]), \
                patch.object(pool, "_groups_of", return_value=set()), \
                patch.object(pool, "home_of", return_value="/home/mxr-1"):
            self.runtime = ensure_person_runtime(self.person)

    def test_the_starters_ready_account_is_used(self):
        from catalyst.tasks import _runtime_preflight

        self.runtime.status = TenantClaudeRuntime.STATUS_READY
        self.runtime.save()
        with patch("claude.service.run_blocking", return_value=MagicMock(failure=None)) as run:
            self.assertEqual(_runtime_preflight(self.person, "group=g"), ("mxr-1", None))
        self.assertEqual(run.call_args.kwargs["run_as_user"], "mxr-1")

    def test_no_ready_account_stops_with_a_reason_and_runs_nothing(self):
        from catalyst.tasks import _runtime_preflight

        with patch("claude.service.run_blocking") as run:
            user, error = _runtime_preflight(self.person, "group=g")
            missing_user, missing = _runtime_preflight(None, "group=g")
        self.assertIsNone(user)
        self.assertTrue(error.startswith("runtime_not_ready"))
        self.assertIsNone(missing_user)
        self.assertTrue(missing.startswith("runtime_missing"))
        run.assert_not_called()

    def test_a_groups_ready_runtime_is_never_used(self):
        from catalyst.tasks import _runtime_preflight
        from groups.models.group import Group

        TenantClaudeRuntime.objects.create(
            tenant_content_type=ContentType.objects.get_for_model(Group),
            tenant_object_id="00000000-0000-0000-0000-000000000009",
            linux_user="grp-user", home_dir="/home/grp-user",
            status=TenantClaudeRuntime.STATUS_READY, allowed_ai_modes=["catalyst.parse"],
        )
        with patch("claude.service.run_blocking") as run:
            user, error = _runtime_preflight(self.person, "group=g")
        self.assertIsNone(user)
        run.assert_not_called()
