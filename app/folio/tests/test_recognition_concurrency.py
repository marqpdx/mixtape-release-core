"""Real PostgreSQL lock/claim race using entirely synthetic Folio material."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from folio.models import Folio, FolioNote
from folio.interpretation import recognition as rec
from folio.interpretation import recognition_contract as wire
from folio.interpretation.lifecycle import begin_reading
from heddle import lifecycle, tasks
from heddle.errors import InterpretationError
from initiatives.models import ActionRun


@override_settings(FOLIO_RECOGNITION_ENABLED=True)
class RecognitionConcurrentClaimsTests(TransactionTestCase):
    def test_two_deliveries_claim_exactly_one_real_child(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        user = get_user_model().objects.create_user(username="claim-race-writer")
        folio = Folio.objects.create(title="Synthetic race", work_type="fiction", sponsor=user,
                                    author=user, submitted_by=user)
        note = FolioNote.objects.create(folio=folio, created_by=user, source_type="text", raw_text="Mara in Paris.")
        reading = rec.make_reading()
        with patch.object(rec, "_dictionary_provider", lambda author, folio: {"revision": 0, "entries": []}), \
             patch("heddle.lifecycle._enqueue"):
            snapshot = begin_reading(author=user, folio_id=folio.pk, note_id=note.pk,
                                     request_id=uuid4(), reading=reading)
            result = lifecycle.execute(author=user, action_run_id=snapshot["action_run_id"], request_id=uuid4(),
                expected_revision=snapshot["revision"], digest=snapshot["source_digest"], reading=reading,
                expected_context_revision=snapshot["context_revision"], context_digest=snapshot["context_digest"])
            child = ActionRun.objects.get(pk=result["execution_action_run_id"])
            barrier = Barrier(2)

            def compete():
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    try:
                        return rec.claim(execution_id=child.pk, person_id=user.pk, tenant_id=child.tenant_id,
                            tenant_namespace=child.tenant_namespace,
                            request_fingerprint=child.request_payload["request_fingerprint"])["status"]
                    except InterpretationError as exc:
                        return exc.code
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _: compete(), range(2)))
            self.assertCountEqual(outcomes, ["claimed", "execution_unavailable"])
            self.assertEqual(ActionRun.objects.count(), 2)
            child.refresh_from_db()
            self.assertEqual(child.status, "running")

    def test_duplicate_callbacks_apply_once_under_the_parent_lock(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        user = get_user_model().objects.create_user(username="callback-race-writer")
        folio = Folio.objects.create(title="Synthetic callbacks", work_type="fiction", sponsor=user,
                                    author=user, submitted_by=user)
        note = FolioNote.objects.create(folio=folio, created_by=user, source_type="text", raw_text="Mara in Paris.")
        reading = rec.make_reading()
        with patch.object(rec, "_dictionary_provider", lambda author, folio: {"revision": 0, "entries": []}), \
             patch("heddle.lifecycle._enqueue"):
            snapshot = begin_reading(author=user, folio_id=folio.pk, note_id=note.pk,
                                     request_id=uuid4(), reading=reading)
            result = lifecycle.execute(author=user, action_run_id=snapshot["action_run_id"], request_id=uuid4(),
                expected_revision=snapshot["revision"], digest=snapshot["source_digest"], reading=reading,
                expected_context_revision=snapshot["context_revision"], context_digest=snapshot["context_digest"])
            child = ActionRun.objects.get(pk=result["execution_action_run_id"])
            rec.claim(execution_id=child.pk, person_id=user.pk, tenant_id=child.tenant_id,
                tenant_namespace=child.tenant_namespace, request_fingerprint=child.request_payload["request_fingerprint"])
            child.refresh_from_db()
            request = child.request_payload["capability_payload"]
            response = {"protocol": wire.PROTOCOL, "profile_digest": wire.PROFILE_DIGEST,
                "binding": request["binding"], "request_fingerprint": wire.digest(request), "candidates": []}
            child.status = "succeeded"
            child.result_payload = {"result": {"findings": response}}
            child.save(update_fields=["status", "result_payload"])
            barrier = Barrier(2)

            def compete():
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    tasks.apply_interpretation(str(child.pk), reading=reading)
                finally:
                    close_old_connections()

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: compete(), range(2)))
            parent = ActionRun.objects.get(pk=child.parent_action_id)
            state = parent.request_payload["interpretation"]
            self.assertEqual(state["status"], "succeeded")
            self.assertTrue(all(step["status"] == "succeeded" for step in state["steps"]))
            self.assertEqual(state["history"], [])
            self.assertEqual(ActionRun.objects.count(), 2)
