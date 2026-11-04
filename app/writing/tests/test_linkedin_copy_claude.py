import json
import uuid
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
)
from writing.linkedin_copy_service import generate_linkedin_copy
from writing.tasks import generate_linkedin_copy_with_claude_code


class LinkedInCopyClaudeServiceTests(SimpleTestCase):
    @patch("writing.linkedin_copy_service.claude_service.terminate_session")
    @patch("writing.linkedin_copy_service.claude_service.run_session_blocking")
    def test_two_pass_generation_reuses_and_terminates_bounded_session(
        self,
        run_session_blocking,
        terminate_session,
    ):
        draft = {
            "hook": "Initial hook",
            "short_synopsis": "Initial synopsis",
            "one_line_takeaway": "Initial takeaway",
            "alt_hook": "Initial alternative",
            "source_claim": "Initial claim",
            "human_stake": "Initial stake",
        }
        reviewed = {**draft, "hook": "Reviewed hook", "short_synopsis": "Reviewed synopsis"}
        run_session_blocking.side_effect = [json.dumps(draft), json.dumps(reviewed)]

        result = generate_linkedin_copy(
            action_run_id="run-123",
            title="Careful systems",
            excerpt="A grounded excerpt.",
            body_preview="The article opening.",
            run_as_user="tenant-user",
            home_dir="/home/tenant-user",
        )

        self.assertEqual(result["hook"], "Reviewed hook")
        self.assertEqual(result["short_synopsis"], "Reviewed synopsis")
        self.assertEqual(result["model_used"], "anthropic-claude-code")
        self.assertEqual(run_session_blocking.call_count, 2)
        first_call = run_session_blocking.call_args_list[0]
        self.assertEqual(first_call.args[0], "linkedin-copy:run-123")
        self.assertEqual(len(first_call.args), 2)  # no cwd: an empty scratch directory
        self.assertEqual(
            first_call.kwargs,
            {"run_as_user": "tenant-user", "home_dir": "/home/tenant-user", "timeout": 180, "tools": ""},
        )
        self.assertEqual(run_session_blocking.call_args_list[1].args[0], "linkedin-copy:run-123")
        terminate_session.assert_called_once_with("linkedin-copy:run-123")

    @patch("writing.linkedin_copy_service.claude_service.terminate_session")
    @patch("writing.linkedin_copy_service.claude_service.run_session_blocking", return_value=None)
    def test_empty_generation_still_terminates_session(self, _run_session, terminate_session):
        with self.assertRaisesRegex(RuntimeError, "generation returned no output"):
            generate_linkedin_copy(
                action_run_id="run-456",
                title="Careful systems",
                excerpt="",
                body_preview="The article opening.",
            )

        terminate_session.assert_called_once_with("linkedin-copy:run-456")


class LinkedInCopyClaudeTaskTests(TestCase):
    """LinkedIn copy runs on the initiator's own Claude account, or not at all (ST-3)."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from tenant_runtime import pool
        from tenant_runtime.models import TenantClaudeRuntime
        from tenant_runtime.resolve import ensure_person_runtime

        self.person = get_user_model().objects.create_user(
            username="writer", email="writer@example.com", password="x")
        with patch.object(pool, "pool_members", return_value=["mxr-1"]), \
                patch.object(pool, "_groups_of", return_value=set()), \
                patch.object(pool, "home_of", return_value="/home/mxr-1"):
            self.runtime = ensure_person_runtime(self.person)
        self.runtime.status = TenantClaudeRuntime.STATUS_READY
        self.runtime.save()
        self.principal = str(self.person.pk)

    def _run(self, action_run, **overrides):
        kwargs = dict(
            action_run_id=str(action_run.id),
            tenant_id=str(action_run.tenant_id),
            tenant_namespace=action_run.tenant_namespace,
            principal_user_id=action_run.initiator_id,
            principal_service_token_id=None,
            request_payload={"title": "A careful article"},
            synopsis_payload={"title": "A careful article", "excerpt": "", "body_preview": ""},
        )
        kwargs.update(overrides)
        return generate_linkedin_copy_with_claude_code.run(**kwargs)

    def _action_run(self, *, approved=True, initiator_id=None):
        return ActionRun.objects.create(
            tool_name="writing.synopsis_linkedin",
            status=ActionRunStatus.RUNNING,
            execution_mode=ActionRunExecutionMode.CLOUD,
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            tenant_namespace="platform:crossroads",
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=initiator_id or self.principal,
            cloud_approved=approved,
            request_payload={"title": "A careful article"},
        )

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_task_completes_action_run_with_claude_result(self, generate_copy):
        action_run = self._action_run()
        generate_copy.return_value = {
            "hook": "Reviewed hook",
            "short_synopsis": "Reviewed synopsis",
            "one_line_takeaway": "People retain judgment.",
            "alt_hook": "A direct alternative.",
            "source_claim": "Tools support judgment.",
            "human_stake": "People remain accountable.",
            "model_used": "anthropic-claude-code",
            "refused": False,
        }

        result = generate_linkedin_copy_with_claude_code.run(
            action_run_id=str(action_run.id),
            tenant_id=str(action_run.tenant_id),
            tenant_namespace=action_run.tenant_namespace,
            principal_user_id=self.principal,
            principal_service_token_id=None,
            request_payload={"title": "A careful article"},
            synopsis_payload={
                "title": "A careful article",
                "excerpt": "A grounded excerpt.",
                "body_preview": "The article opening.",
            },
        )

        action_run.refresh_from_db()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(action_run.status, ActionRunStatus.SUCCEEDED)
        self.assertEqual(action_run.result_payload["short_synopsis"], "Reviewed synopsis")
        self.assertEqual(action_run.result_payload["tool"], "switchboard.synopsis_linkedin")

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_task_refuses_unapproved_cloud_generation(self, generate_copy):
        action_run = self._action_run(approved=False)

        with self.assertRaisesRegex(ValueError, "was not approved"):
            generate_linkedin_copy_with_claude_code.run(
                action_run_id=str(action_run.id),
                tenant_id=str(action_run.tenant_id),
                tenant_namespace=action_run.tenant_namespace,
                principal_user_id=self.principal,
                principal_service_token_id=None,
                request_payload={},
                synopsis_payload={},
            )

        action_run.refresh_from_db()
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(action_run.error_payload["error"], "ValueError")
        generate_copy.assert_not_called()

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_runs_as_the_initiators_pool_user(self, generate_copy):
        generate_copy.return_value = {"short_synopsis": "ok"}
        self._run(self._action_run())
        self.assertEqual(generate_copy.call_args.kwargs["run_as_user"], "mxr-1")
        self.assertEqual(generate_copy.call_args.kwargs["home_dir"], "/home/mxr-1")

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_no_account_fails_plainly_and_never_uses_the_server_login(self, generate_copy):
        self.runtime.delete()
        action_run = self._action_run()
        with self.assertRaises(RuntimeError):
            self._run(action_run)
        action_run.refresh_from_db()
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertIn("Connect your Claude account", action_run.error_payload["message"])
        generate_copy.assert_not_called()

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_an_account_needing_sign_in_stops_the_work(self, generate_copy):
        from tenant_runtime.models import TenantClaudeRuntime

        self.runtime.status = TenantClaudeRuntime.STATUS_LOGIN_REQUIRED
        self.runtime.save()
        action_run = self._action_run()
        with self.assertRaises(RuntimeError):
            self._run(action_run)
        action_run.refresh_from_db()
        self.assertIn("sign in again", action_run.error_payload["message"])
        generate_copy.assert_not_called()

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_a_groups_runtime_is_never_used(self, generate_copy):
        from django.contrib.contenttypes.models import ContentType

        from groups.models.group import Group
        from tenant_runtime.models import TenantClaudeRuntime

        self.runtime.delete()
        TenantClaudeRuntime.objects.create(
            tenant_content_type=ContentType.objects.get_for_model(Group),
            tenant_object_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            linux_user="grp-user", home_dir="/home/grp-user",
            status=TenantClaudeRuntime.STATUS_READY, allowed_ai_modes=["writing.synopsis_linkedin"],
        )
        action_run = self._action_run()
        with self.assertRaises(RuntimeError):
            self._run(action_run)
        generate_copy.assert_not_called()

    @patch("writing.linkedin_copy_service.generate_linkedin_copy")
    def test_an_unknown_initiator_stops_the_work(self, generate_copy):
        action_run = self._action_run(initiator_id="principal-123")
        with self.assertRaises(RuntimeError):
            self._run(action_run, principal_user_id="principal-123")
        generate_copy.assert_not_called()
