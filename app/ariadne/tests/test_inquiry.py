"""P9/P9a: Inquiry Runs and the Review artifact (build spec §19.2-19.3).

Inkwell (service_generate) and Qdrant (get_vectors/embed_texts) are mocked
throughout -- both need a live service this unit suite doesn't stand up.
What's tested here: the Frame consent gate, Gather's dedup/diversity cap,
Map's deterministic clustering, Draft's citation-validation rule (a claim
citing a passage outside the Gather pool is stripped, never kept as a
cited fact), and Curate/Accession's state transitions.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ariadne import inquiry as inquiry_services
from ariadne.models import (
    CorpusSnapshot,
    EvidencePacket,
    Inquiry,
    InquiryReview,
    InquiryRun,
    InquiryTheme,
    Passage,
    SourceDocument,
    SourceRevision,
)

User = get_user_model()


def _make_passage(source_key, text, embedding_status="embedded"):
    document = SourceDocument.objects.create(source_system="puddlejump", source_key=source_key, title=source_key)
    revision = SourceRevision.objects.create(
        document=document, content_hash=source_key, captured_at=timezone.now(), parser_version="1",
    )
    return Passage.objects.create(
        revision=revision, ordinal=1, text=text, content_hash=source_key, embedding_status=embedding_status,
    )


class FrameTestCase(TestCase):
    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="How did Fruition develop?")

    def test_explicit_sub_questions_need_no_model_call(self):
        inquiry = inquiry_services.frame_inquiry(
            self.inquiry, sub_questions=[{"text": "Q1", "approved": False, "search_terms": ["fruition"]}],
        )
        self.assertEqual(inquiry.sub_questions[0]["text"], "Q1")

    def test_no_sub_questions_and_no_model_consent_raises(self):
        with self.assertRaises(inquiry_services.ModelConsentRequired):
            inquiry_services.frame_inquiry(self.inquiry)

    @patch("ariadne.inquiry.service_generate")
    def test_use_model_calls_inkwell(self, mock_generate):
        mock_generate.return_value = {
            "result": {"sub_questions": [{"text": "Q1", "search_terms": ["fruition", "field physics"]}]}
        }
        inquiry = inquiry_services.frame_inquiry(self.inquiry, use_model=True)
        mock_generate.assert_called_once()
        self.assertEqual(inquiry.sub_questions[0]["search_terms"], ["fruition", "field physics"])
        self.assertFalse(inquiry.sub_questions[0]["approved"])

    def test_approve_sub_questions_moves_to_gathering(self):
        inquiry_services.frame_inquiry(
            self.inquiry,
            sub_questions=[
                {"text": "Q1", "approved": False, "search_terms": []},
                {"text": "Q2", "approved": False, "search_terms": []},
            ],
        )
        inquiry = inquiry_services.approve_sub_questions(self.inquiry, approved_texts=["Q1"])
        self.assertTrue(inquiry.sub_questions[0]["approved"])
        self.assertFalse(inquiry.sub_questions[1]["approved"])
        self.assertEqual(inquiry.status, Inquiry.Status.GATHERING)


class GatherTestCase(TestCase):
    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="How did Fruition develop?")
        inquiry_services.frame_inquiry(
            self.inquiry, sub_questions=[{"text": "fruition", "approved": False, "search_terms": []}],
        )
        inquiry_services.approve_sub_questions(self.inquiry, approved_texts=["fruition"])

    def test_gather_requires_a_corpus_snapshot(self):
        with self.assertRaises(ValueError):
            inquiry_services.gather_for_inquiry(self.inquiry)

    def test_gather_requires_approved_sub_questions(self):
        inquiry = inquiry_services.create_inquiry(question="Unframed")
        with self.assertRaises(ValueError):
            inquiry_services.gather_for_inquiry(inquiry)

    @patch("ariadne.inquiry.hybrid_search")
    def test_gather_dedupes_and_caps_per_document(self, mock_search):
        CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        hits = [
            {"passage_id": f"p{i}", "source_key": "doc-a", "excerpt": "...", "found_by": ["lexical"], "vector_score": None}
            for i in range(10)
        ]
        mock_search.return_value = hits

        run = inquiry_services.gather_for_inquiry(self.inquiry)
        self.assertEqual(len(run.gathered_passage_ids), inquiry_services.MAX_PER_DOCUMENT)
        self.assertEqual(run.status, InquiryRun.Status.COMPLETED)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.Status.MAPPING)


class MapTestCase(TestCase):
    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="Q")
        snapshot = CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        self.p1 = _make_passage("a.md", "about fruition")
        self.p2 = _make_passage("b.md", "also about fruition")
        self.p3 = _make_passage("c.md", "something unrelated")
        self.run = InquiryRun.objects.create(
            inquiry=self.inquiry, corpus_snapshot=snapshot,
            gathered_passage_ids=[str(self.p1.id), str(self.p2.id), str(self.p3.id)],
            status=InquiryRun.Status.COMPLETED,
        )

    @patch("ariadne.inquiry.get_vectors")
    def test_clusters_similar_passages_together(self, mock_vectors):
        mock_vectors.return_value = {
            str(self.p1.id): [1.0, 0.0],
            str(self.p2.id): [0.99, 0.01],
            str(self.p3.id): [0.0, 1.0],
        }
        themes = inquiry_services.map_inquiry_run(self.run)
        clusters = [set(t.passage_ids) for t in themes]
        self.assertIn({str(self.p1.id), str(self.p2.id)}, clusters)
        self.assertIn({str(self.p3.id)}, clusters)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.Status.DRAFTING)

    @patch("ariadne.inquiry.embed_texts")
    @patch("ariadne.inquiry.get_vectors", return_value={})
    def test_missing_vectors_are_embedded_on_the_fly(self, mock_vectors, mock_embed):
        mock_embed.return_value = [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]
        themes = inquiry_services.map_inquiry_run(self.run)
        mock_embed.assert_called_once()
        self.assertEqual(sum(len(t.passage_ids) for t in themes), 3)

    @patch("ariadne.inquiry.get_vectors")
    def test_rerunning_map_replaces_prior_themes(self, mock_vectors):
        mock_vectors.return_value = {
            str(self.p1.id): [1.0, 0.0], str(self.p2.id): [1.0, 0.0], str(self.p3.id): [0.0, 1.0],
        }
        inquiry_services.map_inquiry_run(self.run)
        first_count = InquiryTheme.objects.filter(run=self.run).count()
        inquiry_services.map_inquiry_run(self.run)
        second_count = InquiryTheme.objects.filter(run=self.run).count()
        self.assertEqual(first_count, second_count)


class ThemePacketTestCase(TestCase):
    def test_assemble_theme_packet(self):
        inquiry = inquiry_services.create_inquiry(question="Q")
        snapshot = CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        p1 = _make_passage("a.md", "about fruition")
        run = InquiryRun.objects.create(inquiry=inquiry, corpus_snapshot=snapshot, gathered_passage_ids=[str(p1.id)])
        theme = InquiryTheme.objects.create(run=run, passage_ids=[str(p1.id)], label="Fruition's origin")

        packet = inquiry_services.assemble_theme_packet(theme)
        self.assertEqual(packet.subject_kind, EvidencePacket.SubjectKind.INQUIRY_THEME)
        self.assertEqual(packet.inquiry_run_id, run.id)
        self.assertIsNone(packet.run_id)
        self.assertIn("Fruition's origin", packet.summary)


class DraftTestCase(TestCase):
    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="How did Fruition develop?")
        snapshot = CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        self.p1 = _make_passage("a.md", "Fruition grew from the Spatial ADR's field physics.")
        self.run = InquiryRun.objects.create(
            inquiry=self.inquiry, corpus_snapshot=snapshot, gathered_passage_ids=[str(self.p1.id)],
        )
        InquiryTheme.objects.create(run=self.run, passage_ids=[str(self.p1.id)], rank=0)

    def test_draft_requires_use_model(self):
        with self.assertRaises(inquiry_services.ModelConsentRequired):
            inquiry_services.draft_review(self.run)

    @patch("ariadne.inquiry.service_generate")
    def test_valid_citation_is_kept(self, mock_generate):
        mock_generate.return_value = {
            "result": {"claims": [{"text": "Fruition grew from field physics.", "passage_ids": [str(self.p1.id)]}]}
        }
        review = inquiry_services.draft_review(self.run, use_model=True)
        self.assertEqual(review.uncited_claim_count, 0)
        self.assertEqual(review.citations[0]["passage_ids"], [str(self.p1.id)])
        self.assertIn(str(self.p1.id)[:8], review.body_markdown)
        self.inquiry.refresh_from_db()
        self.assertEqual(self.inquiry.status, Inquiry.Status.CURATING)

    @patch("ariadne.inquiry.service_generate")
    def test_citation_outside_pool_is_stripped_not_kept(self, mock_generate):
        """§9 4E: an invented/out-of-pool passage id must not survive into
        a claim presented as cited fact."""
        mock_generate.return_value = {
            "result": {"claims": [{"text": "An unsupported claim.", "passage_ids": ["not-in-the-pool"]}]}
        }
        review = inquiry_services.draft_review(self.run, use_model=True)
        self.assertEqual(review.citations[0]["passage_ids"], [])
        self.assertTrue(review.citations[0]["interpretation"])
        self.assertEqual(review.uncited_claim_count, 1)
        self.assertIn("interpretation, uncited", review.body_markdown)


class CurateAndAccessionTestCase(TestCase):
    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="Q")
        snapshot = CorpusSnapshot.objects.create(manifest_hash="x", source_revision_ids=[], captured_at=timezone.now())
        self.p1 = _make_passage("a.md", "Some evidence.")
        self.run = InquiryRun.objects.create(
            inquiry=self.inquiry, corpus_snapshot=snapshot, gathered_passage_ids=[str(self.p1.id)],
        )
        self.review = InquiryReview.objects.create(
            inquiry=self.inquiry, run=self.run, version=1,
            citations=[
                {
                    "id": "c0", "text": "A claim.", "passage_ids": [str(self.p1.id)],
                    "interpretation": False, "status": "proposed", "amended_text": None,
                },
            ],
        )

    def test_strike_removes_claim_from_rendered_body(self):
        review = inquiry_services.curate_citation(self.review, citation_id="c0", action="strike")
        self.assertEqual(review.citations[0]["status"], "struck")
        self.assertNotIn("A claim.", review.body_markdown)

    def test_amend_replaces_rendered_text(self):
        review = inquiry_services.curate_citation(
            self.review, citation_id="c0", action="amend", amended_text="A corrected claim.",
        )
        self.assertEqual(review.citations[0]["amended_text"], "A corrected claim.")
        self.assertIn("A corrected claim.", review.body_markdown)

    def test_unknown_citation_id_raises(self):
        with self.assertRaises(ValueError):
            inquiry_services.curate_citation(self.review, citation_id="nope", action="accept")

    def test_accession_sets_standing_review_and_done_status(self):
        inquiry = inquiry_services.accession_review(self.review)
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, InquiryReview.Status.CURATED)
        self.assertEqual(inquiry.standing_review_id, self.review.id)
        self.assertEqual(inquiry.status, Inquiry.Status.DONE)

    def test_accession_records_lineage_when_superseding_a_prior_standing_review(self):
        inquiry_services.accession_review(self.review)

        second_review = InquiryReview.objects.create(
            inquiry=self.inquiry, run=self.run, version=2,
            citations=[
                {
                    "id": "c0", "text": "An updated claim.", "passage_ids": [str(self.p1.id)],
                    "interpretation": False, "status": "proposed", "amended_text": None,
                },
            ],
        )
        inquiry = inquiry_services.accession_review(second_review)
        second_review.refresh_from_db()

        self.assertEqual(second_review.superseded_review_id, self.review.id)
        self.assertEqual(inquiry.standing_review_id, second_review.id)

    def test_first_accession_leaves_superseded_review_null(self):
        inquiry_services.accession_review(self.review)
        self.review.refresh_from_db()
        self.assertIsNone(self.review.superseded_review_id)
