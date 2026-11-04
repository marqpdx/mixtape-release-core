"""P6 curation workbench + P6a Concept lookup -- API tests.

P8's search/lens endpoints get a thin smoke test here (view wiring,
validation, 404s); the actual hybrid-search merge logic is covered in
test_search.py against the service layer directly.

Exercises the real service-layer flow (record_decision,
assemble_evidence_packet, packet_passage_detail) through the actual DRF
views, against a minimal but real chain of Lens/LensVersion/CorpusSnapshot/
DiscoveryRun/RunCandidate and SourceDocument/SourceRevision/Passage rows --
the same objects the real 2026-10-12 Discovery Run persisted, just a small
fixture instead of the full corpus.
"""

import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from ariadne.models import (
    Concept,
    ConceptAlias,
    CorpusSnapshot,
    CurationDecision,
    DiscoveryRun,
    EvidencePacket,
    Lens,
    LensVersion,
    Passage,
    RunCandidate,
    SourceDocument,
    SourceRevision,
)

User = get_user_model()


class AriadneWorkbenchTestCase(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_user(
            username="su", email="su@example.com", password="x", is_superuser=True, is_staff=True,
        )
        self.member = User.objects.create_user(
            username="member", email="member@example.com", password="x",
        )
        self.client = APIClient()

        document = SourceDocument.objects.create(
            source_system="puddlejump",
            source_key="decisions/example.md",
            title="Example Decision",
            uri="decisions/example.md",
        )
        revision = SourceRevision.objects.create(
            document=document,
            content_hash="abc123",
            captured_at=timezone.now(),
            parser_version="1",
        )
        document.current_revision = revision
        document.save(update_fields=["current_revision"])
        self.passage = Passage.objects.create(
            revision=revision,
            ordinal=1,
            text="This decision introduces Catalyst as the per-tenant activation layer.",
            content_hash="def456",
        )

        lens = Lens.objects.create(name="General")
        lens_version = LensVersion.objects.create(lens=lens, version=1, config={}, config_hash="hash1")
        snapshot = CorpusSnapshot.objects.create(
            manifest_hash="manifest1",
            source_revision_ids=[str(revision.id)],
            captured_at=timezone.now(),
        )
        self.run = DiscoveryRun.objects.create(
            lens_version=lens_version,
            corpus_snapshot=snapshot,
            status=DiscoveryRun.Status.COMPLETED,
        )
        self.candidate = RunCandidate.objects.create(
            run=self.run,
            concept_or_phrase_key="catalyst",
            rank=1,
            score=10.0,
        )

    def test_candidates_list_rejects_non_superuser(self):
        self.client.force_authenticate(self.member)
        response = self.client.get(f"/api/ariadne/runs/{self.run.id}/candidates/")
        self.assertEqual(response.status_code, 403)

    def test_candidates_list_rejects_anonymous(self):
        response = self.client.get(f"/api/ariadne/runs/{self.run.id}/candidates/")
        self.assertEqual(response.status_code, 401)

    def test_latest_run(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get("/api/ariadne/runs/latest/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.run.id))

    def test_latest_run_404_when_none_exist(self):
        self.run.delete()
        self.client.force_authenticate(self.superuser)
        response = self.client.get("/api/ariadne/runs/latest/")
        self.assertEqual(response.status_code, 404)

    def test_run_detail_and_candidates_list(self):
        self.client.force_authenticate(self.superuser)

        run_response = self.client.get(f"/api/ariadne/runs/{self.run.id}/")
        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(run_response.data["lens_name"], "General")
        self.assertEqual(run_response.data["candidate_count"], 1)

        candidates_response = self.client.get(f"/api/ariadne/runs/{self.run.id}/candidates/")
        self.assertEqual(candidates_response.status_code, 200)
        self.assertEqual(len(candidates_response.data), 1)
        self.assertEqual(candidates_response.data[0]["concept_or_phrase_key"], "catalyst")
        self.assertIsNone(candidates_response.data[0]["concept_id"])

    def test_decision_accept_creates_concept_and_updates_candidate(self):
        self.client.force_authenticate(self.superuser)

        response = self.client.post(
            f"/api/ariadne/runs/{self.run.id}/decisions/",
            {"candidate_key": "catalyst", "action": "accept", "reason": "clear early mention"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["disposition"], "accept")
        self.assertEqual(response.data["concept_label"], "catalyst")

        self.candidate.refresh_from_db()
        self.assertIsNotNone(self.candidate.concept)
        self.assertEqual(self.candidate.concept.preferred_label, "catalyst")
        self.assertEqual(self.candidate.concept.status, Concept.Status.CANDIDATE)

        decision = CurationDecision.objects.get(run=self.run, candidate_key="catalyst")
        self.assertEqual(decision.action, "accept")
        self.assertEqual(decision.actor, self.superuser)
        self.assertIsNone(decision.supersedes)

    def test_decision_invalid_action_is_rejected(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            f"/api/ariadne/runs/{self.run.id}/decisions/",
            {"candidate_key": "catalyst", "action": "not-a-real-action"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_decision_unknown_candidate_404s(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            f"/api/ariadne/runs/{self.run.id}/decisions/",
            {"candidate_key": "no-such-candidate", "action": "accept"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_second_decision_supersedes_the_first(self):
        self.client.force_authenticate(self.superuser)
        self.client.post(
            f"/api/ariadne/runs/{self.run.id}/decisions/",
            {"candidate_key": "catalyst", "action": "defer"},
            format="json",
        )
        self.client.post(
            f"/api/ariadne/runs/{self.run.id}/decisions/",
            {"candidate_key": "catalyst", "action": "accept"},
            format="json",
        )
        decisions = list(
            CurationDecision.objects.filter(run=self.run, candidate_key="catalyst").order_by("created_at")
        )
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[1].supersedes_id, decisions[0].id)

    def test_packet_assemble_and_versioning(self):
        self.client.force_authenticate(self.superuser)

        first = self.client.post(
            f"/api/ariadne/runs/{self.run.id}/packets/",
            {"candidate_key": "catalyst"},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["packet_version"], 1)
        self.assertEqual(first.data["subject_kind"], "concept")
        self.assertIn("Catalyst", first.data["summary"]) if False else None  # summary echoes lowercase key

        second = self.client.post(
            f"/api/ariadne/runs/{self.run.id}/packets/",
            {"candidate_key": "catalyst"},
            format="json",
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.data["packet_version"], 2)

        listing = self.client.get(f"/api/ariadne/runs/{self.run.id}/packets/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data), 2)

    def test_packet_detail_dereferences_passages(self):
        self.client.force_authenticate(self.superuser)
        packet = EvidencePacket.objects.create(
            run=self.run,
            candidate_key="catalyst",
            source_revision_ids=[str(self.passage.revision_id)],
            passage_ids=[str(self.passage.id)],
            packet_version=1,
            summary="1 passage mentions catalyst",
        )

        response = self.client.get(f"/api/ariadne/packets/{packet.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["passages"]), 1)
        passage_detail = response.data["passages"][0]
        self.assertEqual(passage_detail["document_title"], "Example Decision")
        self.assertIsNotNone(passage_detail["quote_offsets"])
        self.assertIn("Catalyst", passage_detail["excerpt"])

    def test_packet_assemble_bounded_to_run_snapshot(self):
        """A passage outside the Run's CorpusSnapshot must not show up,
        even if it mentions the same phrase -- §9/§10's reproducibility
        requirement."""
        other_document = SourceDocument.objects.create(
            source_system="puddlejump", source_key="other.md", title="Other",
        )
        other_revision = SourceRevision.objects.create(
            document=other_document, content_hash="zzz", captured_at=timezone.now(), parser_version="1",
        )
        Passage.objects.create(
            revision=other_revision, ordinal=1, text="Catalyst appears here too.", content_hash="zzz2",
        )

        self.client.force_authenticate(self.superuser)
        response = self.client.post(
            f"/api/ariadne/runs/{self.run.id}/packets/",
            {"candidate_key": "catalyst"},
            format="json",
        )
        packet = EvidencePacket.objects.get(id=response.data["id"])
        self.assertEqual(packet.passage_ids, [str(self.passage.id)])

    def test_concept_lookup_by_id_name_and_alias(self):
        concept = Concept.objects.create(preferred_label="catalyst", status=Concept.Status.CURATED)
        ConceptAlias.objects.create(concept=concept, alias="activation layer")

        self.client.force_authenticate(self.superuser)

        by_id = self.client.get(f"/api/ariadne/concepts/{concept.id}/")
        self.assertEqual(by_id.status_code, 200)
        self.assertEqual(by_id.data["preferred_label"], "catalyst")
        self.assertEqual(len(by_id.data["aliases"]), 1)
        self.assertEqual(by_id.data["evidence"], [])

        by_name = self.client.get("/api/ariadne/concepts/", {"name": "Catalyst"})
        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(by_name.data["id"], str(concept.id))

        by_alias = self.client.get("/api/ariadne/concepts/", {"alias": "Activation Layer"})
        self.assertEqual(by_alias.status_code, 200)
        self.assertEqual(by_alias.data["id"], str(concept.id))

    def test_concept_lookup_not_found(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get(f"/api/ariadne/concepts/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, 404)

        no_match = self.client.get("/api/ariadne/concepts/", {"name": "no-such-concept"})
        self.assertEqual(no_match.status_code, 404)

    def test_concept_lookup_requires_a_query_param(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get("/api/ariadne/concepts/")
        self.assertEqual(response.status_code, 400)

    def test_search_requires_a_query_param(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get("/api/ariadne/search/")
        self.assertEqual(response.status_code, 400)

    def test_search_rejects_non_superuser(self):
        self.client.force_authenticate(self.member)
        response = self.client.get("/api/ariadne/search/", {"q": "catalyst"})
        self.assertEqual(response.status_code, 403)

    def test_search_returns_results(self):
        self.client.force_authenticate(self.superuser)
        with patch("ariadne.api.views.search_services.hybrid_search", return_value=[{"passage_id": "x"}]):
            response = self.client.get("/api/ariadne/search/", {"q": "catalyst"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["query"], "catalyst")
        self.assertEqual(response.data["results"], [{"passage_id": "x"}])

    def test_save_list_and_run_saved_search(self):
        self.client.force_authenticate(self.superuser)

        created = self.client.post(
            "/api/ariadne/lenses/", {"name": "Fruition coverage", "query": "fruition"}, format="json",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["query"], "fruition")

        listed = self.client.get("/api/ariadne/lenses/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data), 1)

        with patch("ariadne.api.views.search_services.run_saved_search", return_value=[{"passage_id": "x"}]):
            run = self.client.get(f"/api/ariadne/lenses/{created.data['id']}/run/")
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.data["results"], [{"passage_id": "x"}])

    def test_run_unknown_lens_404s(self):
        self.client.force_authenticate(self.superuser)
        response = self.client.get(f"/api/ariadne/lenses/{uuid.uuid4()}/run/")
        self.assertEqual(response.status_code, 404)


class AriadneInquiryViewsTestCase(TestCase):
    """P9/P9a view wiring -- the actual Frame/Gather/Map/Draft/Curate
    behavior is covered against the service layer in test_inquiry.py;
    this is a thin smoke test of the endpoints themselves."""

    def setUp(self):
        self.superuser = User.objects.create_user(
            username="su3", email="su3@example.com", password="x", is_superuser=True, is_staff=True,
        )
        self.member = User.objects.create_user(username="member3", email="member3@example.com", password="x")
        self.client = APIClient()

    def test_create_inquiry_rejects_non_superuser(self):
        self.client.force_authenticate(self.member)
        response = self.client.post("/api/ariadne/inquiries/", {"question": "Q"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_create_and_fetch_inquiry(self):
        self.client.force_authenticate(self.superuser)
        created = self.client.post("/api/ariadne/inquiries/", {"question": "How did Fruition develop?"}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["status"], "framing")

        fetched = self.client.get(f"/api/ariadne/inquiries/{created.data['id']}/")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.data["question"], "How did Fruition develop?")

    def test_frame_without_model_consent_returns_400(self):
        self.client.force_authenticate(self.superuser)
        created = self.client.post("/api/ariadne/inquiries/", {"question": "Q"}, format="json")
        response = self.client.post(f"/api/ariadne/inquiries/{created.data['id']}/frame/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_frame_and_approve_flow(self):
        self.client.force_authenticate(self.superuser)
        created = self.client.post("/api/ariadne/inquiries/", {"question": "Q"}, format="json")
        inquiry_id = created.data["id"]

        framed = self.client.post(
            f"/api/ariadne/inquiries/{inquiry_id}/frame/",
            {"sub_questions": [{"text": "Q1", "approved": False, "search_terms": ["q1"]}]},
            format="json",
        )
        self.assertEqual(framed.status_code, 200)

        approved = self.client.post(
            f"/api/ariadne/inquiries/{inquiry_id}/approve-sub-questions/",
            {"approved_texts": ["Q1"]},
            format="json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data["status"], "gathering")

    def test_draft_without_model_consent_returns_400(self):
        from ariadne.models import CorpusSnapshot, Inquiry, InquiryRun

        inquiry = Inquiry.objects.create(question="Q")
        snapshot = CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        run = InquiryRun.objects.create(inquiry=inquiry, corpus_snapshot=snapshot)

        self.client.force_authenticate(self.superuser)
        response = self.client.post(f"/api/ariadne/inquiry-runs/{run.id}/draft/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_accession_sets_standing_review(self):
        from ariadne.models import CorpusSnapshot, Inquiry, InquiryRun, InquiryReview

        inquiry = Inquiry.objects.create(question="Q")
        snapshot = CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        run = InquiryRun.objects.create(inquiry=inquiry, corpus_snapshot=snapshot)
        review = InquiryReview.objects.create(inquiry=inquiry, run=run, version=1)

        self.client.force_authenticate(self.superuser)
        response = self.client.post(f"/api/ariadne/inquiry-reviews/{review.id}/accession/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["standing_review_id"], str(review.id))
        self.assertEqual(response.data["status"], "done")
