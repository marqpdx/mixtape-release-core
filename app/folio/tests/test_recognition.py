"""Synthetic local lifecycle tests; no model, broker or network."""
from uuid import uuid4
from unittest.mock import patch
import time

import jwt
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from folio.models import Folio, FolioNote
from folio.interpretation import recognition as rec
from folio.interpretation import recognition_contract as wire
from folio.interpretation.lifecycle import begin_reading
from folio.interpretation.strategy import make_reading as composed_reading
from folio.interpretation.lifecycle import context_provider as composed_context
from folio.services.local_policy import change_local_only
from heddle import lifecycle, tasks
from heddle.errors import InterpretationError
from initiatives.models import ActionRun

SECRET = "synthetic-recognition-auth-secret-at-least-32-bytes"


@override_settings(FOLIO_RECOGNITION_ENABLED=True,
                   SWITCHBOARD_CORE_JWT_SECRETS={"test-switchboard": SECRET})
class RecognitionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="recognition-writer")
        self.other = get_user_model().objects.create_user(username="recognition-other")
        self.folio = Folio.objects.create(title="Quiet City", work_type="fiction",
            sponsor=self.user, author=self.user, submitted_by=self.user)
        self.note = FolioNote.objects.create(folio=self.folio, created_by=self.user,
            source_type="text", raw_text="🦉 Mara meets Lucy in Café.")
        self.reading = rec.make_reading()
        self.provider = patch.object(rec, "_dictionary_provider", lambda author, folio: {"revision": 0, "entries": []})
        self.provider.start()
        self.addCleanup(self.provider.stop)
        self.enqueue = patch("heddle.lifecycle._enqueue")
        self.send = self.enqueue.start()
        self.addCleanup(self.enqueue.stop)

    def begin(self, reading=None):
        return begin_reading(author=self.user, folio_id=self.folio.pk, note_id=self.note.pk,
            request_id=uuid4(), reading=reading or self.reading)

    def execute(self, snapshot=None, request_id=None):
        snap = snapshot or self.begin()
        with self.captureOnCommitCallbacks(execute=True):
            result = lifecycle.execute(author=self.user, action_run_id=snap["action_run_id"],
                request_id=request_id or uuid4(), expected_revision=snap["revision"], digest=snap["source_digest"],
                expected_context_revision=snap["context_revision"], context_digest=snap["context_digest"],
                reading=self.reading, consent=False)
        child = ActionRun.objects.get(pk=result["execution_action_run_id"])
        return child

    def claim(self, child, **overrides):
        args = dict(execution_id=child.pk, person_id=self.user.pk, tenant_id=child.tenant_id,
            tenant_namespace=child.tenant_namespace, request_fingerprint=child.request_payload["request_fingerprint"])
        args.update(overrides)
        return rec.claim(**args)

    def succeed(self, child):
        request = child.request_payload["capability_payload"]
        response = {"protocol": wire.PROTOCOL, "profile_digest": wire.PROFILE_DIGEST,
            "binding": request["binding"], "request_fingerprint": wire.digest(request), "candidates": []}
        child.status = "succeeded"
        child.result_payload = {"result": {"findings": response, "provenance": {"provider": "untrusted"}}}
        child.save(update_fields=["status", "result_payload"])

    def test_local_child_has_no_cloud_approval_or_runtime_and_only_reference_is_queued(self):
        child = self.execute()
        self.assertEqual(child.execution_mode, "local")
        self.assertFalse(child.cloud_approved)
        self.assertFalse(child.approval_payload)
        self.assertEqual(ActionRun.objects.count(), 2)
        queued = self.send.call_args.args[1]["capability_payload"]
        self.assertEqual(set(queued), {"execution_action_run_id", "request_fingerprint"})
        self.assertEqual(self.claim(child)["status"], "claimed")
        child.refresh_from_db()
        self.assertEqual(child.status, "running")
        with self.assertRaisesMessage(InterpretationError, "execution_unavailable"):
            self.claim(child)

    def test_execute_replay_keeps_one_child_and_one_dispatch(self):
        snapshot = self.begin()
        key = uuid4()
        first = self.execute(snapshot, key)
        second = self.execute(snapshot, key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.send.call_count, 1)

    def test_apply_replay_reports_partial_with_successful_actual_steps(self):
        child = self.execute()
        self.claim(child)
        child.refresh_from_db()
        self.succeed(child)
        for _ in range(2):
            tasks.apply_interpretation(str(child.pk), reading=self.reading)
        parent = ActionRun.objects.get(pk=child.parent_action_id)
        snapshot = lifecycle.snapshot(parent, reading=self.reading)
        self.assertEqual(snapshot["status"], "partial")
        self.assertEqual(snapshot["strategy_execution_status"], "succeeded")
        self.assertEqual(snapshot["semantic_interpretation"], "not_run")
        self.assertTrue(all(s["status"] == "succeeded" for s in snapshot["steps"]))
        self.assertEqual(snapshot["steps"][2]["provenance"]["provider"], "selene")
        self.assertEqual(self.claim(child)["status"], "terminal")
        self.note.refresh_from_db()
        self.assertEqual(self.note.mentions, [])

    def test_success_without_actual_claim_cannot_apply(self):
        child = self.execute()
        self.succeed(child)
        tasks.apply_interpretation(str(child.pk), reading=self.reading)
        parent = ActionRun.objects.get(pk=child.parent_action_id)
        self.assertEqual(parent.request_payload["interpretation"]["error"], "invalid_output")

    def test_failed_model_leaves_checked_step_unattempted(self):
        child = self.execute()
        self.claim(child)
        child.refresh_from_db()
        child.status = "failed"
        child.error_payload = {"error": "source_too_long"}
        child.save(update_fields=["status", "error_payload"])
        tasks.apply_interpretation(str(child.pk), reading=self.reading)
        parent = ActionRun.objects.get(pk=child.parent_action_id)
        state = parent.request_payload["interpretation"]
        self.assertEqual(state["steps"][-1]["status"], "not_attempted")
        self.assertEqual(state["error"], "source_too_long")
        self.assertEqual(lifecycle.snapshot(parent, reading=self.reading)["status"], "failed")

    def test_claim_rejects_other_person_wrong_tenant_and_fingerprint(self):
        child = self.execute()
        for changed in ({"person_id": self.other.pk}, {"tenant_id": uuid4()},
                        {"tenant_namespace": "group:other"}, {"request_fingerprint": "a" * 64}):
            with self.assertRaises(InterpretationError):
                self.claim(child, **changed)
        child.refresh_from_db()
        self.assertEqual(child.status, "pending")

    def test_claim_rechecks_active_person_moved_note_and_context(self):
        child = self.execute()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(InterpretationError): self.claim(child)
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        self.folio.title = "Changed"
        self.folio.save()
        with self.assertRaises(InterpretationError): self.claim(child)
        self.note.deleted_at = __import__('django.utils.timezone', fromlist=['now']).now()
        self.note.save(update_fields=["deleted_at"])
        with self.assertRaises(InterpretationError): self.claim(child)

    def test_changed_context_after_claim_never_overwrites_findings(self):
        child = self.execute()
        self.claim(child)
        child.refresh_from_db()
        self.succeed(child)
        self.folio.title = "Changed"
        self.folio.save()
        tasks.apply_interpretation(str(child.pk), reading=self.reading)
        parent = ActionRun.objects.get(pk=child.parent_action_id)
        self.assertEqual(parent.request_payload["interpretation"]["status"], "superseded")
        self.assertIsNone(parent.request_payload["interpretation"]["findings"])

    def test_missing_dictionary_refuses_instead_of_empty_result(self):
        with patch.object(rec, "_dictionary_provider", None):
            with self.assertRaisesMessage(InterpretationError, "dictionary_unavailable"): self.begin()
        self.assertFalse(ActionRun.objects.exists())

    @override_settings(FOLIO_RECOGNITION_ENABLED=False)
    def test_disabled_execution_has_no_child(self):
        with self.assertRaisesMessage(InterpretationError, "backend_unavailable"): self.execute()
        self.assertEqual(ActionRun.objects.count(), 1)

    def test_disabled_after_enqueue_records_denial_without_host_execution(self):
        child = self.execute()
        with override_settings(FOLIO_RECOGNITION_ENABLED=False):
            result = self.claim(child)
            self.assertEqual(result["status"], "terminal")
            self.assertEqual(result["error"], {"error": "backend_unavailable"})
        tasks.apply_interpretation(str(child.pk), reading=self.reading)
        parent = ActionRun.objects.get(pk=child.parent_action_id)
        self.assertEqual(parent.request_payload["interpretation"]["steps"][2]["status"], "failed")

    def test_local_policy_api_is_strict_and_owner_scoped(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = f"/api/folio/folios/{self.folio.pk}/local-policy"
        body = {"request_id": str(uuid4()), "expected_revision": 0, "local_only": True}
        self.assertEqual(client.post(url, {**body, "local_only": "false"}, format="json").status_code, 400)
        self.assertEqual(client.post(url, body, format="json").status_code, 200)
        client.force_authenticate(self.other)
        self.assertEqual(client.post(url, body, format="json").status_code, 404)

    def test_corrections_share_aggregate_budget_and_are_preserved_on_refusal(self):
        snapshot = self.begin()
        lifecycle.correct(author=self.user, action_run_id=snapshot["action_run_id"], request_id=uuid4(),
            expected_revision=0, reading=self.reading, text="a" * 4000)
        parent = ActionRun.objects.get(pk=snapshot["action_run_id"])
        snapshot = {**lifecycle.snapshot(parent, reading=self.reading), "action_run_id": str(parent.pk)}
        with self.assertRaisesMessage(InterpretationError, "source_too_long"): self.execute(snapshot)
        parent.refresh_from_db()
        self.assertEqual(len(parent.request_payload["interpretation"]["sources"]), 2)
        self.assertEqual(ActionRun.objects.count(), 1)

    def test_existing_composed_chain_has_explicit_strategy_conflict(self):
        self.begin(composed_reading(capability="test.fiction", context_provider=composed_context))
        with self.assertRaisesMessage(InterpretationError, "strategy_conflict"): self.begin()

    def test_claim_endpoint_requires_correct_dedicated_scope_and_kid(self):
        child = self.execute()
        client = APIClient()
        url = f"/api/folio/recognition-executions/{child.pk}/claim"
        body = {"person_id": str(self.user.pk), "tenant_id": str(child.tenant_id),
            "tenant_namespace": child.tenant_namespace, "request_fingerprint": child.request_payload["request_fingerprint"]}
        now = int(time.time())
        for scope, kid, expected in [("orchestration:write", "test-switchboard", 403),
                ("folio:recognition:claim", "unknown", 403), ("folio:recognition:claim", "test-switchboard", 200)]:
            token = jwt.encode({"sub": "switchboard", "iss": "mixtape", "aud": "switchboard-core",
                "iat": now, "nbf": now-5, "exp": now+120, "scopes": [scope]}, SECRET,
                algorithm="HS256", headers={"kid": kid})
            response = client.post(url, body, format="json", HTTP_AUTHORIZATION="Bearer " + token)
            self.assertEqual(response.status_code, expected, response.data)

    def test_local_policy_owner_revision_replay_and_strict_boolean(self):
        key = uuid4()
        args = dict(author=self.user, folio_id=self.folio.pk, local_only=True, expected_revision=0, request_id=key)
        result = change_local_only(**args)
        self.assertEqual(change_local_only(**args), result)
        self.assertTrue(result["local_only"])
        for changed in ({"author": self.other}, {"local_only": False}, {"local_only": "false"}):
            with self.assertRaises(InterpretationError): change_local_only(**{**args, **changed})
        self.assertFalse(ActionRun.objects.exists())

    def test_current_folio_flag_blocks_composed_cloud_dispatch(self):
        reading = composed_reading(capability="test.fiction", context_provider=composed_context)
        snap = self.begin(reading)
        self.folio.local_only = True
        self.folio.save(update_fields=["local_only"])
        # Refresh the context explicitly, then still refuse despite consent.
        from heddle.ordered import refresh_context
        self.folio.refresh_from_db()
        self.folio.context_revision += 1
        self.folio.save(update_fields=["context_revision"])
        snap = refresh_context(author=self.user, action_run_id=snap["action_run_id"],
            expected_context_revision=snap["context_revision"], reading=reading)
        with self.assertRaisesMessage(InterpretationError, "policy_forbids_cloud"):
            lifecycle.execute(author=self.user, action_run_id=snap["weave_action_run_id"], request_id=uuid4(),
                expected_revision=snap["revision"], digest=snap["source_digest"], reading=reading,
                expected_context_revision=snap["context_revision"], context_digest=snap["context_digest"], consent=True)
