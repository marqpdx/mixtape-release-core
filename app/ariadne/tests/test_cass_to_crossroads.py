"""Cass-to-Crossroads result flow (build-plan-cass-to-crossroads-result-flow.md).

Exercises export.build_review_export_package and
import_review.import_review_package against the same Django test
database standing in for "two separate databases" -- good enough to
prove the round-trip shape and the id-based upsert/replace semantics;
it does not stand up a second real database.
"""

from django.test import TestCase
from django.utils import timezone

from ariadne import inquiry as inquiry_services
from ariadne.export import build_review_export_package
from ariadne.import_review import ReviewImportError, import_review_package
from ariadne.models import CorpusSnapshot, Inquiry, InquiryReview, InquiryRun, InquiryTheme, Passage, SourceDocument, SourceRevision


def _make_passage(source_key, text):
    document = SourceDocument.objects.create(source_system="puddlejump", source_key=source_key, title=source_key)
    revision = SourceRevision.objects.create(
        document=document, content_hash=source_key, captured_at=timezone.now(), parser_version="1",
    )
    return Passage.objects.create(revision=revision, ordinal=1, text=text, content_hash=source_key)


class ExportReviewPackageTestCase(TestCase):
    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="How did Fruition develop?")
        self.snapshot = CorpusSnapshot.objects.create(
            manifest_hash="sha256:x", source_revision_ids=[], captured_at=timezone.now(),
        )
        self.passage = _make_passage("a.md", "Some evidence.")
        self.run = InquiryRun.objects.create(
            inquiry=self.inquiry, corpus_snapshot=self.snapshot, gathered_passage_ids=[str(self.passage.id)],
        )
        InquiryTheme.objects.create(run=self.run, label="Theme A", passage_ids=[str(self.passage.id)], rank=0)
        self.review = InquiryReview.objects.create(
            inquiry=self.inquiry, run=self.run, version=1,
            citations=[
                {
                    "id": "c0", "text": "A claim.", "passage_ids": [str(self.passage.id)],
                    "interpretation": False, "status": "accepted", "amended_text": None,
                },
            ],
        )
        inquiry_services.accession_review(self.review)
        self.review.refresh_from_db()

    def test_citations_carry_resolved_source_text(self):
        package = build_review_export_package(self.review)
        citation = package["review"]["citations"][0]
        self.assertEqual(len(citation["sources"]), 1)
        source = citation["sources"][0]
        self.assertEqual(source["text"], "Some evidence.")
        self.assertEqual(source["document_title"], "a.md")

    def test_package_carries_corpus_snapshot_for_the_run_fk(self):
        package = build_review_export_package(self.review)
        self.assertEqual(package["corpus_snapshot"]["id"], str(self.snapshot.id))
        self.assertEqual(package["run"]["corpus_snapshot_id"], str(self.snapshot.id))

    def test_package_carries_theme(self):
        package = build_review_export_package(self.review)
        self.assertEqual(len(package["themes"]), 1)
        self.assertEqual(package["themes"][0]["label"], "Theme A")


class ImportReviewPackageTestCase(TestCase):
    """Imports into the *same* test database the package was built from --
    the tables are otherwise empty of these rows, so update_or_create
    exercises the create path here; a second import of a changed package
    (below) exercises the replace path."""

    def setUp(self):
        self.inquiry = inquiry_services.create_inquiry(question="How did Fruition develop?")
        self.snapshot = CorpusSnapshot.objects.create(
            manifest_hash="sha256:x", source_revision_ids=[], captured_at=timezone.now(),
        )
        self.passage = _make_passage("a.md", "Some evidence.")
        self.run = InquiryRun.objects.create(
            inquiry=self.inquiry, corpus_snapshot=self.snapshot, gathered_passage_ids=[str(self.passage.id)],
        )
        self.review = InquiryReview.objects.create(
            inquiry=self.inquiry, run=self.run, version=1,
            citations=[
                {
                    "id": "c0", "text": "A claim.", "passage_ids": [str(self.passage.id)],
                    "interpretation": False, "status": "accepted", "amended_text": None,
                },
            ],
        )
        inquiry_services.accession_review(self.review)
        self.review.refresh_from_db()
        self.package = build_review_export_package(self.review)

    def test_import_sets_standing_review(self):
        # Clear the standing pointer first to simulate a fresh Crossroads row.
        self.inquiry.standing_review = None
        self.inquiry.save(update_fields=["standing_review"])

        imported = import_review_package(self.package)
        self.inquiry.refresh_from_db()
        self.assertEqual(imported.id, self.review.id)
        self.assertEqual(self.inquiry.standing_review_id, self.review.id)

    def test_reimport_replaces_rather_than_duplicates(self):
        import_review_package(self.package)
        before_count = InquiryReview.objects.filter(id=self.review.id).count()

        changed_package = dict(self.package)
        changed_package["review"] = {**self.package["review"], "body_markdown": "Changed."}
        import_review_package(changed_package)

        self.assertEqual(before_count, 1)
        self.assertEqual(InquiryReview.objects.filter(id=self.review.id).count(), 1)
        self.review.refresh_from_db()
        self.assertEqual(self.review.body_markdown, "Changed.")

    def test_unsupported_schema_version_raises(self):
        bad_package = {**self.package, "schema_version": 999}
        with self.assertRaises(ReviewImportError):
            import_review_package(bad_package)

    def test_missing_required_field_raises(self):
        bad_package = dict(self.package)
        del bad_package["review"]
        with self.assertRaises(ReviewImportError):
            import_review_package(bad_package)
