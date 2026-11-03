import copy
import json
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, SimpleTestCase, override_settings
from jsonschema import ValidationError

from claude.service import ClaudeResult
from heddle import lifecycle, tasks, steps
from heddle.bundle import bundle_identity, shape_schema, validate_sighting
from heddle.contract import Reading
from heddle.errors import InterpretationError
from heddle.ordered import refresh_context
from initiatives.models import ActionRun, ActionRunStatus
from tenant_runtime.models import TenantClaudeRuntime

RESULT = {"sightings": [{"sighting_id": "c1", "shape_id": "writing.character", "shape_version": "0.1.0",
    "confidence": "medium", "source_locator": [{"source_ref": "note:1", "source_revision": 0,
    "start": 2, "end": 6, "quote": "Mara"}], "uncertain": [], "name_as_said": "Mara"}], "questions": []}
SCHEMA = {"type": "object", "required": ["sightings", "questions"], "additionalProperties": False,
          "properties": {"sightings": {"type": "array"}, "questions": {"type": "array"}}}


def make_reading(context_provider):
    return Reading(capability="test_reading", tool_name="test.reading", version="0.1.0", prompt_version="0.1.0",
        units=(), cloud_setting_name="TEST_READING_CLOUD", build_prompt=lambda *a: "legacy unused",
        response_schema=SCHEMA, validate_findings=lambda result, sources: result,
        resolvable_shape_ids=frozenset(), callback_task="test.apply", context_provider=context_provider,
        strategy_id="test.strategy", strategy_version="0.1.0", steps=(
            steps.Step("prepare", "1", "deterministic", "source/1", "prepared/1", run=lambda data: {"prepared": True}),
            steps.Step("cues", "1", "deterministic", "prepared/1", "cues/1", requires=("prepare",), run=lambda data: {"cues": []}),
            steps.Step("semantic", "1", "model", "cues/1", "reading/1", requires=("cues",),
                       build_prompt=lambda data: json.dumps(data, ensure_ascii=False), response_schema=SCHEMA),
            steps.Step("assemble", "1", "deterministic", "reading/1", "checked/1", requires=("semantic",),
                       run=lambda data: data["outputs"]["semantic"])))


class BundleTests(SimpleTestCase):
    def test_bundle_is_versioned_and_lookup_cannot_mutate_cached_schema(self):
        self.assertEqual(len(bundle_identity()["digest"]), 64)
        schema = shape_schema("writing.character", "0.1.0")
        schema["properties"].clear()
        self.assertIn("name_as_said", shape_schema("writing.character", "0.1.0")["properties"])

    def test_unknown_version_and_unknown_field_fail(self):
        with self.assertRaises(ValidationError): shape_schema("writing.character", "99")
        with self.assertRaisesMessage(ValidationError, "invented"):
            validate_sighting({**RESULT["sightings"][0], "invented": True})

    def test_optional_absence_and_uncertainty_are_valid(self):
        sighting = copy.deepcopy(RESULT["sightings"][0])
        sighting["uncertain"] = [{"field": "name_as_said", "reason": "unclear audio"}]
        validate_sighting(sighting)

    def test_invalid_step_order_rejected(self):
        reading = make_reading(None)
        with self.assertRaises(ValueError): steps.definitions(replace(reading, steps=tuple(reversed(reading.steps))))


@override_settings(TEST_READING_CLOUD=True)
class OrderedReadingTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_superuser(username="ordered-reader", password="test", email="reader@example.test")
        self.context = {"revision": 0, "type": "fiction", "title": "Quiet City", "bundle_digest": bundle_identity()["digest"]}
        self.reading = make_reading(lambda author, parent: self.context)
        self.runtime = TenantClaudeRuntime.objects.create(tenant_content_type=ContentType.objects.get_for_model(self.author),
            tenant_object_id=self.author.pk, linux_user="reader", home_dir="/home/reader",
            status=TenantClaudeRuntime.STATUS_READY, allowed_ai_modes=[self.reading.capability])
        def factory():
            return ActionRun.objects.create(tool_name=self.reading.tool_name, tenant_id=uuid4(),
                tenant_namespace="platform:crossroads", initiator_type="human", initiator_id=str(self.author.pk), status="pending")
        self.parent, self.initial = lifecycle.begin(author=self.author, request_id=uuid4(), reading=self.reading,
            parent_factory=factory, source_ref="note:1", source_text="🦉 Mara returns", conflict_key="note_id", conflict_value="1")

    def execute(self, request_id=None, state=None, **overrides):
        state = state or self.initial
        kwargs = dict(author=self.author, action_run_id=self.parent.pk, request_id=request_id or uuid4(),
            expected_revision=state["revision"], digest=state["source_digest"], reading=self.reading, consent=True,
            expected_context_revision=state["context_revision"], context_digest=state["context_digest"])
        kwargs.update(overrides)
        with patch("heddle.lifecycle.celery_app.send_task") as send:
            with self.captureOnCommitCallbacks(execute=True):
                result = lifecycle.execute(**kwargs)
        return result, send.call_count

    def start_worker(self, state):
        child = ActionRun.objects.get(pk=state["execution_action_run_id"])
        child.status = ActionRunStatus.RUNNING
        child.result_payload = {"dispatch": {"cloud_approved": True, "source_digest": state["source_digest"], "revision": state["revision"]}}
        child.save()
        return child

    def run_worker(self, child, result=RESULT, side_effect=None):
        with patch("claude.service.run_blocking", return_value=ClaudeResult(output=json.dumps(result), elapsed_ms=1), side_effect=side_effect) as model:
            tasks.run_cloud_interpretation(action_run_id=str(child.pk), reading=self.reading,
                apply_fn=lambda cid: tasks.apply_interpretation(cid, reading=self.reading))
        self.parent.refresh_from_db()
        return lifecycle.snapshot(self.parent, reading=self.reading), model

    def test_ordered_steps_have_only_one_actual_child_and_bound_approval(self):
        running, count = self.execute()
        self.assertEqual(count, 1)
        self.assertEqual([r["status"] for r in running["steps"]], ["succeeded", "succeeded", "running", "pending"])
        self.assertEqual(self.parent.child_actions.count(), 1)
        child = self.parent.child_actions.get()
        self.assertEqual(child.approval_payload["context_digest"], self.initial["context_digest"])
        self.assertEqual(child.approval_payload["steps"][2]["id"], "semantic")
        done, model = self.run_worker(self.start_worker(running))
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["findings"], RESULT)
        self.assertEqual([r["status"] for r in done["steps"]], ["succeeded"] * 4)
        self.assertEqual(model.call_args.kwargs["run_as_user"], "reader")
        self.assertEqual(self.parent.status, ActionRunStatus.PENDING)

    def test_idempotent_execute_never_dispatches_twice(self):
        request = uuid4()
        first, _ = self.execute(request)
        second, count = self.execute(request)
        self.assertEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(count, 0)
        self.assertEqual(self.parent.child_actions.count(), 1)

    def test_missing_context_consent_or_runtime_sends_nothing(self):
        for overrides in ({"consent": False}, {"context_digest": "wrong"}, {"expected_context_revision": None}):
            with self.assertRaises(InterpretationError): self.execute(**overrides)
        self.runtime.delete()
        with self.assertRaisesMessage(InterpretationError, "runtime_missing"): self.execute()
        self.assertFalse(self.parent.child_actions.exists())

    def test_context_change_before_dispatch_requires_explicit_refresh_and_consent(self):
        self.context = {**self.context, "revision": 1, "title": "Changed"}
        with self.assertRaisesMessage(InterpretationError, "context_conflict"): self.execute()
        updated = refresh_context(author=self.author, action_run_id=self.parent.pk,
            expected_context_revision=0, reading=self.reading)
        with self.assertRaises(InterpretationError): self.execute(state=updated, consent=False)
        running, _ = self.execute(state=updated)
        self.assertEqual(running["context_revision"], 1)

    def test_context_change_before_worker_never_calls_model(self):
        running, _ = self.execute()
        child = self.start_worker(running)
        self.context = {**self.context, "revision": 1}
        _, model = self.run_worker(child)
        model.assert_not_called()
        child.refresh_from_db()
        self.assertEqual(child.error_payload["error"], "context_conflict")

    def test_changed_prompt_or_approval_is_rejected_before_model(self):
        running, _ = self.execute()
        child = self.start_worker(running)
        child.request_payload["capability_payload"]["prompt"] = "tampered"
        child.save()
        _, model = self.run_worker(child)
        model.assert_not_called()

    def test_context_changed_during_model_never_applies(self):
        running, _ = self.execute()
        child = self.start_worker(running)
        def change(*args, **kwargs):
            self.context = {**self.context, "revision": 1}
            return ClaudeResult(output=json.dumps(RESULT), elapsed_ms=1)
        state, _ = self.run_worker(child, side_effect=change)
        self.assertIsNone(state["findings"])
        child.refresh_from_db()
        self.assertEqual(child.status, ActionRunStatus.SUCCEEDED)

    def test_correction_keeps_attempt_history_and_ignores_old_callback(self):
        running, _ = self.execute()
        child = self.start_worker(running)
        changed = lifecycle.correct(author=self.author, action_run_id=self.parent.pk, request_id=uuid4(),
            expected_revision=0, reading=self.reading, text="Actually, her name is Mira.")
        self.assertEqual(changed["history"][0]["attempt_id"], running["attempt_id"])
        self.assertEqual(changed["sources"][0]["text"], "🦉 Mara returns")
        state, model = self.run_worker(child)
        model.assert_not_called()
        self.assertEqual(state["revision"], 1)
        self.assertIsNone(state["findings"])

    def test_failed_model_retains_deterministic_output_and_no_fake_assembly(self):
        running, _ = self.execute()
        state, _ = self.run_worker(self.start_worker(running), result={"wrong": True})
        self.assertEqual(state["status"], "partial")
        self.assertEqual([r["status"] for r in state["steps"]], ["succeeded", "succeeded", "failed", "not_attempted"])
        self.assertEqual(state["steps"][0]["output"], {"prepared": True})

    def test_bad_unicode_span_is_not_checked_success(self):
        output = copy.deepcopy(RESULT)
        output["sightings"][0]["source_locator"][0].update(start=3, end=7)
        running, _ = self.execute()
        state, _ = self.run_worker(self.start_worker(running), result=output)
        self.assertEqual(state["status"], "partial")
        self.assertIsNone(state["findings"])

    def test_retry_retains_succeeded_sightings_and_old_attempt(self):
        running, _ = self.execute()
        self.run_worker(self.start_worker(running))
        retried, _ = self.execute()
        self.assertEqual(retried["history"][0]["findings"], RESULT)
        self.assertNotEqual(retried["history"][0]["attempt_id"], retried["attempt_id"])

    def test_skipped_optional_step_and_blocked_prerequisite_are_honest(self):
        reading = make_reading(lambda *args: self.context)
        self.reading = replace(reading, steps=(replace(reading.steps[0], should_run=lambda data: False), *reading.steps[1:]))
        self.parent.request_payload["interpretation"]["plan"] = steps.plan_identity(self.reading)
        self.parent.save()
        state, _ = self.execute()
        self.assertEqual([r["status"] for r in state["steps"]], ["skipped", "not_attempted", "not_attempted", "not_attempted"])
        self.assertEqual(state["status"], "partial")
        self.assertFalse(self.parent.child_actions.exists())

    def test_two_actual_model_steps_get_two_children_in_order(self):
        original = self.reading
        second = replace(original.steps[2], id="semantic_second", requires=("semantic",))
        assembly = replace(original.steps[3], requires=("semantic_second",),
                           run=lambda data: data["outputs"]["semantic_second"])
        self.reading = replace(original, steps=(*original.steps[:3], second, assembly))
        self.parent.request_payload["interpretation"]["plan"] = steps.plan_identity(self.reading)
        self.parent.save()
        running, _ = self.execute()
        with patch("heddle.lifecycle.celery_app.send_task") as send:
            with self.captureOnCommitCallbacks(execute=True):
                intermediate, _ = self.run_worker(self.start_worker(running))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.parent.child_actions.count(), 2)
        self.assertEqual([r["status"] for r in intermediate["steps"]], ["succeeded"] * 3 + ["running", "pending"])
        done, _ = self.run_worker(self.start_worker(intermediate))
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(self.parent.child_actions.count(), 2)

    def test_dispatch_failure_is_partial_and_records_model_failure(self):
        with patch("heddle.lifecycle.celery_app.send_task", side_effect=RuntimeError("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                lifecycle.execute(author=self.author, action_run_id=self.parent.pk, request_id=uuid4(),
                    expected_revision=0, digest=self.initial["source_digest"], reading=self.reading, consent=True,
                    expected_context_revision=0, context_digest=self.initial["context_digest"])
        self.parent.refresh_from_db()
        state = lifecycle.snapshot(self.parent, reading=self.reading)
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["steps"][2]["error"]["code"], "dispatch_unavailable")
        self.assertEqual(state["steps"][3]["status"], "not_attempted")

    def test_context_change_must_increment_revision(self):
        self.context = {**self.context, "title": "different"}
        with self.assertRaisesMessage(InterpretationError, "context_revision_required"):
            refresh_context(author=self.author, action_run_id=self.parent.pk, expected_context_revision=0, reading=self.reading)

    def test_runtime_becomes_unavailable_before_worker(self):
        running, _ = self.execute()
        child = self.start_worker(running)
        self.runtime.delete()
        state, model = self.run_worker(child)
        model.assert_not_called()
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["steps"][2]["error"]["code"], "runtime_missing")

    def test_schema_unknown_field_fails_checked_assembly(self):
        output = copy.deepcopy(RESULT)
        output["sightings"][0]["invented"] = True
        running, _ = self.execute()
        state, _ = self.run_worker(self.start_worker(running), result=output)
        self.assertEqual(state["steps"][3]["status"], "failed")
        self.assertIsNone(state["findings"])

    def test_definition_change_before_worker_sends_nothing(self):
        running, _ = self.execute()
        self.reading = replace(self.reading, prompt_version="0.2.0")
        state, model = self.run_worker(self.start_worker(running))
        model.assert_not_called()
        self.assertEqual(state["status"], "superseded")

    def test_prompt_budget_is_explicit_and_never_truncates(self):
        self.reading = replace(self.reading, max_prompt_chars=1)
        with self.assertRaisesMessage(InterpretationError, "prompt_too_long"):
            self.execute()
        self.assertFalse(self.parent.child_actions.exists())

    def test_typed_reference_failure_prevents_checked_output(self):
        self.reading = replace(self.reading, reference_fields=(("participant_ids", ("writing.character",)),))
        self.parent.request_payload["interpretation"]["plan"] = steps.plan_identity(self.reading)
        self.parent.save()
        output = copy.deepcopy(RESULT)
        passage = output["sightings"][0]["source_locator"][0]
        output["sightings"].append({"sighting_id": "scene1", "shape_id": "writing.scene", "shape_version": "0.1.0",
            "source_locator": [passage], "passage": passage, "text": "Mara", "uncertain": [], "confidence": "low",
            "participant_ids": ["scene1"]})
        running, _ = self.execute()
        state, _ = self.run_worker(self.start_worker(running), result=output)
        self.assertEqual(state["steps"][3]["status"], "failed")
        self.assertIsNone(state["findings"])
