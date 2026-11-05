"""Atrium Dialogues on the owner's own account, on the runtime worker (Service Trust ST-3 Part B)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from atrium import turns
from atrium.ai import service as atrium_service
from atrium.models import (
    CloudAgentSession,
    Dialogue,
    DialogueEntry,
    DialogueEntryStatus,
    DialogueEntryType,
    DialogueRole,
    Distillate,
    DistillateStatus,
)
from cloud_agents.constants import PROVIDER_ANTHROPIC_CLAUDE_CODE as CLAUDE
from cloud_agents.constants import PROVIDER_OPENAI_CODEX as CODEX
from claude import service as claude_service
from initiatives.models import ActionRun, ActionRunStatus
from profiles.services.profiles import ensure_user_profile
from tenant_runtime import pool
from tenant_runtime.models import TenantClaudeRuntime, TenantCodexRuntime
from tenant_runtime.resolve import PERSON_DEFAULT_MODES, ensure_person_runtime


def _events(*pairs):
    def fake(provider, prompt, *, cwd, runtime, resume_id):
        fake.calls.append({"provider": provider, "prompt": prompt, "cwd": cwd, "resume_id": resume_id})
        yield from pairs
    fake.calls = []
    return fake


class DialogueTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ada", email="ada@example.com", password="x")
        self.profile = ensure_user_profile(self.user)
        self.dialogue = Dialogue.objects.create(member=self.profile)

    def _ready(self, provider_model=TenantClaudeRuntime, provider="claude"):
        with patch.object(pool, "pool_members", return_value=["mxr-01"]), \
                patch.object(pool, "_groups_of", return_value=set()), \
                patch.object(pool, "home_of", return_value="/home/mxr-01"):
            runtime = ensure_person_runtime(self.user, provider)
        runtime.status = provider_model.STATUS_READY
        runtime.save()
        return runtime


class StartTurnTests(DialogueTestCase):
    def test_without_an_account_the_message_is_kept_and_the_reply_says_why(self):
        with patch("atrium.tasks.run_dialogue_turn.apply_async") as queued, \
                self.captureOnCommitCallbacks(execute=True):
            reply = turns.start_turn(self.dialogue, self.user, "hello")

        queued.assert_not_called()
        self.assertEqual(reply.status, DialogueEntryStatus.FAILED)
        self.assertEqual(reply.error_code, "runtime_missing")
        person = DialogueEntry.objects.get(dialogue=self.dialogue, role=DialogueRole.USER)
        self.assertEqual(person.content, "hello")
        self.assertFalse(ActionRun.objects.exists())

    def test_with_a_ready_account_the_reply_is_queued_on_the_runtime_worker(self):
        self._ready()
        with patch("atrium.tasks.run_dialogue_turn.apply_async") as queued, \
                self.captureOnCommitCallbacks(execute=True):
            reply = turns.start_turn(self.dialogue, self.user, "hello", CLAUDE)

        self.assertEqual(reply.status, DialogueEntryStatus.PENDING)
        self.assertEqual(reply.speaker, CLAUDE)
        queued.assert_called_once_with(kwargs={"entry_id": str(reply.id)}, queue="runtime", routing_key="runtime")
        run = reply.action_run
        self.assertEqual(run.tool_name, "atrium.dialogue")
        self.assertEqual(run.initiator_id, str(self.user.pk))
        self.assertTrue(run.cloud_approved)
        self.dialogue.refresh_from_db()
        self.assertEqual(self.dialogue.title, "hello")

    def test_picking_another_agent_makes_it_the_dialogues_next(self):
        self._ready(TenantCodexRuntime, "codex")
        with patch("atrium.tasks.run_dialogue_turn.apply_async"), self.captureOnCommitCallbacks(execute=True):
            reply = turns.start_turn(self.dialogue, self.user, "second opinion?", CODEX)
        self.assertEqual(reply.speaker, CODEX)
        self.dialogue.refresh_from_db()
        self.assertEqual(self.dialogue.ai_provider, CODEX)

    def test_new_person_runtimes_include_atrium(self):
        self.assertIn("atrium.dialogue", PERSON_DEFAULT_MODES)


class RunTurnTests(DialogueTestCase):
    def setUp(self):
        super().setUp()
        self.runtime = self._ready()

    def _start(self, message="hello", provider=CLAUDE):
        with patch("atrium.tasks.run_dialogue_turn.apply_async"), self.captureOnCommitCallbacks(execute=True):
            return turns.start_turn(self.dialogue, self.user, message, provider)

    def test_a_reply_is_written_as_the_person_and_remembered_for_next_time(self):
        reply = self._start()
        fake = _events(("provider_session", "sess-1"), ("delta", "Hi "), ("delta", "Ada."))
        with patch.object(turns, "_provider_events", fake):
            self.assertEqual(turns.run_turn(str(reply.id)), "done")

        reply.refresh_from_db()
        self.assertEqual(reply.status, DialogueEntryStatus.DONE)
        self.assertEqual(reply.content, "Hi Ada.")
        self.assertIsNone(fake.calls[0]["resume_id"])
        self.assertIn("Person: hello", fake.calls[0]["prompt"])
        agent = CloudAgentSession.objects.get(dialogue=self.dialogue, provider=CLAUDE)
        self.assertEqual(agent.provider_session_id, "sess-1")
        self.assertEqual(agent.seen_through, reply.created_at)
        self.assertEqual(agent.linux_user, "mxr-01")
        self.assertEqual(reply.action_run.status, ActionRunStatus.SUCCEEDED)

    def test_the_next_turn_resumes_in_the_same_working_directory(self):
        first = self._start("one")
        fake = _events(("provider_session", "sess-1"), ("delta", "ok"))
        with patch.object(turns, "_provider_events", fake):
            turns.run_turn(str(first.id))
            second = self._start("two")
            turns.run_turn(str(second.id))
        self.assertEqual(fake.calls[1]["resume_id"], "sess-1")
        self.assertEqual(fake.calls[0]["cwd"], fake.calls[1]["cwd"])
        self.assertTrue(fake.calls[1]["prompt"].endswith("two"))

    def test_a_returning_agent_is_told_what_another_agent_said(self):
        self._ready(TenantCodexRuntime, "codex")
        with patch.object(turns, "_provider_events", _events(("provider_session", "c-1"), ("delta", "Rust, I think."))):
            turns.run_turn(str(self._start("which language?").id))
        with patch.object(turns, "_provider_events", _events(("provider_session", "x-1"), ("delta", "Go, actually."))):
            turns.run_turn(str(self._start("second opinion?", CODEX).id))
        back = _events(("delta", "Fair point."))
        with patch.object(turns, "_provider_events", back):
            turns.run_turn(str(self._start("what do you make of that?").id))

        prompt = back.calls[0]["prompt"]
        self.assertEqual(back.calls[0]["resume_id"], "c-1")
        self.assertIn("Person: second opinion?", prompt)
        self.assertIn("Codex: Go, actually.", prompt)
        self.assertNotIn("Rust, I think.", prompt)  # its own earlier reply is in its own session

    def test_a_signed_out_account_says_so(self):
        reply = self._start()
        with patch.object(turns, "_provider_events", _events(("error", "Invalid API key · Please run /login"))), \
                patch("tenant_runtime.tasks.verify_claude_runtime", return_value="needs_sign_in"):
            self.assertEqual(turns.run_turn(str(reply.id)), "failed")
        reply.refresh_from_db()
        self.assertEqual(reply.error_code, "runtime_not_ready")
        self.assertEqual(reply.action_run.status, ActionRunStatus.FAILED)

    def test_a_session_that_cant_be_resumed_starts_fresh_once(self):
        CloudAgentSession.objects.create(
            dialogue=self.dialogue, provider=CLAUDE, provider_session_id="gone",
            linux_user="mxr-01", seen_through=timezone.now() - timedelta(minutes=5),
        )
        reply = self._start()
        calls = []

        def fake(provider, prompt, *, cwd, runtime, resume_id):
            calls.append(resume_id)
            if resume_id:
                yield ("error", "No conversation found with session ID: gone")
            else:
                yield ("provider_session", "new")
                yield ("delta", "Back again.")

        with patch.object(turns, "_provider_events", fake):
            self.assertEqual(turns.run_turn(str(reply.id)), "done")
        self.assertEqual(calls, ["gone", None])
        self.assertEqual(CloudAgentSession.objects.get(dialogue=self.dialogue).provider_session_id, "new")

    def test_a_document_reply_is_unwrapped(self):
        reply = self._start()
        text = '<document title="Plan">\n# Steps\n</document>'
        with patch.object(turns, "_provider_events", _events(("delta", text))):
            turns.run_turn(str(reply.id))
        reply.refresh_from_db()
        self.assertEqual(reply.entry_type, DialogueEntryType.DOCUMENT)
        self.assertEqual(reply.document_title, "Plan")
        self.assertEqual(reply.content, "# Steps")


class FollowReplyTests(DialogueTestCase):
    def test_follow_sends_new_text_then_the_finished_entry(self):
        from atrium.api.views import follow_reply

        reply = DialogueEntry.objects.create(
            dialogue=self.dialogue, role=DialogueRole.ASSISTANT, speaker=CLAUDE,
            status=DialogueEntryStatus.DONE, content="All done.",
        )
        events = [json.loads(chunk[6:]) for chunk in follow_reply(reply.id) if chunk.startswith(b"data: ")]
        self.assertEqual([e["type"] for e in events], ["final", "done"])
        self.assertEqual(events[0]["content"], "All done.")

    def test_follow_names_why_a_reply_stopped(self):
        from atrium.api.views import follow_reply

        reply = DialogueEntry.objects.create(
            dialogue=self.dialogue, role=DialogueRole.ASSISTANT, speaker=CLAUDE,
            status=DialogueEntryStatus.FAILED, error_code="runtime_not_ready",
        )
        events = [json.loads(chunk[6:]) for chunk in follow_reply(reply.id) if chunk.startswith(b"data: ")]
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "runtime_not_ready")
        self.assertIn("Settings", events[-1]["detail"])


class DistillTests(DialogueTestCase):
    def test_distill_runs_on_the_owners_account(self):
        from atrium.tasks import run_distill
        from initiatives.models import Initiative

        from django.contrib.contenttypes.models import ContentType

        initiative = Initiative.objects.create(
            title="Plans",
            sponsor_content_type=ContentType.objects.get_for_model(self.profile),
            sponsor_object_id=self.profile.pk,
        )
        distillate = Distillate.objects.create(
            initiative=initiative, dialogue=self.dialogue, title="Summary", status=DistillateStatus.PENDING,
        )
        DialogueEntry.objects.create(dialogue=self.dialogue, role=DialogueRole.USER, content="We chose Rust.")
        with patch("atrium.turns.run_once", return_value="We chose Rust.") as once:
            self.assertEqual(run_distill(str(distillate.id)), DistillateStatus.DONE)
        once.assert_called_once()
        distillate.refresh_from_db()
        self.assertEqual(distillate.body, "We chose Rust.")


class StreamJsonEventsTests(SimpleTestCase):
    def _run(self, *objs):
        state = {"done": False}
        out = []
        for obj in objs:
            out.extend(claude_service._stream_json_events(obj, state))
        return out, state

    def test_text_session_and_result(self):
        out, state = self._run(
            {"type": "system", "subtype": "init", "session_id": "abc"},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}},
            {"type": "result", "usage": {"input_tokens": 2000}},
        )
        self.assertEqual(out[0], ("provider_session", "abc"))
        self.assertEqual(out[1], ("delta", "Hi"))
        self.assertEqual(out[2][0], "context_status")
        self.assertTrue(state["done"])

    def test_error_result(self):
        out, state = self._run({"type": "result", "is_error": True, "result": "Please run /login"})
        self.assertEqual(out, [("error", "Please run /login")])
        self.assertTrue(state["done"])

    def test_dialogue_turns_keep_their_session_file(self):
        with patch.object(claude_service, "_cli_supports", return_value=True):
            self.assertIn("--no-session-persistence", claude_service._lockdown_args("Read"))
            self.assertNotIn("--no-session-persistence", claude_service._lockdown_args("Read", persist_session=True))

    def test_stream_turn_refuses_without_a_person(self):
        with self.assertRaises(ValueError):
            next(claude_service.stream_turn("hi", cwd="/tmp", run_as_user=""))


class NoServerLoginTests(SimpleTestCase):
    def test_atrium_has_no_server_login_paths_left(self):
        for name in ("ClaudeCodeAdapter", "CodexExecAdapter", "AtriumAnthropicAdapter", "AtriumAIService", "PUDDLEJUMP_GROUPS"):
            self.assertFalse(hasattr(atrium_service, name), name)

    def test_atrium_tasks_route_to_the_runtime_worker(self):
        from mixtape.celery_app import app

        for name in ("atrium.tasks.run_dialogue_turn", "atrium.tasks.run_distill", "atrium.tasks.keeper_compact_task"):
            self.assertEqual(app.conf.task_routes[name]["queue"], "runtime", name)


class OpenInitiativeTests(DialogueTestCase):
    def _initiative(self, sponsor):
        from django.contrib.contenttypes.models import ContentType
        from initiatives.models import Initiative

        return Initiative.objects.create(
            title="Marketing",
            sponsor_content_type=ContentType.objects.get_for_model(sponsor),
            sponsor_object_id=sponsor.pk,
        )

    def _open(self, initiative, user=None):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user or self.user)
        return client.post(f"/api/atrium/initiatives/{initiative.id}/open")

    def test_opening_an_empty_initiative_starts_one_dialogue(self):
        initiative = self._initiative(self.profile)
        first = self._open(initiative)
        self.assertEqual(first.status_code, 201)
        again = self._open(initiative)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data["id"], first.data["id"])

    def test_opening_lands_on_the_most_recent_dialogue(self):
        initiative = self._initiative(self.profile)
        Dialogue.objects.create(member=self.profile, initiative=initiative, title="Plans")
        recent = Dialogue.objects.create(
            member=self.profile, initiative=initiative, title="Later", last_activity_at=timezone.now()
        )
        self.assertEqual(self._open(initiative).data["id"], str(recent.id))

    def test_a_personal_dialogue_lives_in_initiative_zero_and_atrium_starts_there(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.user)
        made = client.post("/api/atrium/dialogues/new", {}, format="json").data
        self.assertTrue(made["initiative_is_personal"])
        self.assertEqual(client.get("/api/atrium/me/start").data["id"], made["id"])

    def test_someone_elses_initiative_is_not_found(self):
        other = get_user_model().objects.create_user(username="bo", email="bo@example.com", password="x")
        initiative = self._initiative(ensure_user_profile(other))
        self.assertEqual(self._open(initiative).status_code, 404)

    def test_the_list_filters_by_initiative(self):
        from rest_framework.test import APIClient

        initiative = self._initiative(self.profile)
        inside = Dialogue.objects.create(member=self.profile, initiative=initiative)
        client = APIClient()
        client.force_authenticate(self.user)
        data = client.get(f"/api/atrium/dialogues/?initiative_id={initiative.id}").data
        rows = data["results"] if isinstance(data, dict) else data
        self.assertEqual([row["id"] for row in rows], [str(inside.id)])


class CheckpointTests(DialogueTestCase):
    def setUp(self):
        super().setUp()
        self.runtime = self._ready()

    _start = RunTurnTests._start

    def test_after_a_compact_the_next_turn_starts_fresh_from_the_checkpoint(self):
        from atrium.tasks import run_compact

        first = self._start("We chose Rust for the menu-bar tool.")
        fake = _events(("provider_session", "sess-1"), ("delta", "Rust it is."))
        with patch.object(turns, "_provider_events", fake):
            turns.run_turn(str(first.id))

        checkpoint = DialogueEntry.objects.create(
            dialogue=self.dialogue,
            role=DialogueRole.ASSISTANT,
            entry_type=DialogueEntryType.CHECKPOINT,
            status=DialogueEntryStatus.PENDING,
        )
        with patch.object(turns, "run_once", return_value="Decided: Rust.") as once:
            self.assertEqual(run_compact(str(checkpoint.id)), "done")
        self.assertIn("We chose Rust", once.call_args.args[1])
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.content, "Decided: Rust.")

        second = self._start("What next?")
        with patch.object(turns, "_provider_events", fake):
            turns.run_turn(str(second.id))
        prompt = fake.calls[1]["prompt"]
        self.assertIsNone(fake.calls[1]["resume_id"])
        self.assertIn("Decided: Rust.", prompt)
        self.assertNotIn("We chose Rust", prompt)


class InitiativeMemoryTests(DialogueTestCase):
    def test_the_initiative_memory_opens_every_dialogue_in_it(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.user)
        first = client.post("/api/atrium/dialogues/new", {}, format="json").data
        saved = client.patch(
            f"/api/atrium/dialogues/{first['id']}/memory", {"memory": "We write in Rust."}, format="json"
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.data["initiative_is_personal"])

        second = Dialogue.objects.get(pk=client.post("/api/atrium/dialogues/new", {}, format="json").data["id"])
        prompt, _ = atrium_service.build_opening_prompt(second, "hello", before=timezone.now())
        self.assertIn("We write in Rust.", prompt)


class DialogueSearchTests(DialogueTestCase):
    def test_search_finds_my_dialogue_by_what_was_said_not_someone_elses(self):
        from rest_framework.test import APIClient

        mine = Dialogue.objects.create(member=self.profile, title="Tools")
        DialogueEntry.objects.create(dialogue=mine, role=DialogueRole.USER, content="Which Rust crates for a menu-bar app?")
        Dialogue.objects.create(member=self.profile, title="Garden")
        other = get_user_model().objects.create_user(username="bo", email="bo@example.com", password="x")
        theirs = Dialogue.objects.create(member=ensure_user_profile(other), title="Rust")
        DialogueEntry.objects.create(dialogue=theirs, role=DialogueRole.USER, content="Rust everywhere")

        client = APIClient()
        client.force_authenticate(self.user)
        results = client.get("/api/atrium/search", {"q": "rust"}).data["results"]
        self.assertEqual([row["id"] for row in results], [str(mine.id)])
        self.assertIn("«Rust»", results[0]["snippet"])
