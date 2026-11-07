"""Cass-to-Crossroads result flow (build-plan-cass-to-crossroads-result-flow.md).

Exercises export.build_review_export_package and
import_review.import_review_package against the same Django test
database standing in for "two separate databases" -- good enough to
prove the round-trip shape and the id-based upsert/replace semantics;
it does not stand up a second real database.
"""

import time

import jwt
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

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

    def test_non_curated_review_is_refused(self):
        draft_package = dict(self.package)
        draft_package["review"] = {**self.package["review"], "status": InquiryReview.Status.DRAFT}
        with self.assertRaises(ReviewImportError):
            import_review_package(draft_package)


_ARIADNE_PUBLISH_SETTINGS = dict(
    ARIADNE_PUBLISH_JWT_SECRET="test-ariadne-publish-secret",
    ARIADNE_PUBLISH_JWT_ALG="HS256",
    ARIADNE_PUBLISH_JWT_ISS="cass-ariadne",
    ARIADNE_PUBLISH_JWT_AUD="crossroads-ariadne-import",
)


def _mint(secret, *, iss="cass-ariadne", aud="crossroads-ariadne-import", scopes=("ariadne:publish",)):
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "cass-ariadne-export", "scopes": list(scopes),
            "iat": now, "nbf": now, "exp": now + 300, "iss": iss, "aud": aud,
        },
        secret, algorithm="HS256",
    )


@override_settings(ARIADNE_ENABLED=True, **_ARIADNE_PUBLISH_SETTINGS)
class ReviewImportViewAuthTestCase(TestCase):
    """Handoff 2026-11-07, item 4: this flow's authentication must verify
    only against ARIADNE_PUBLISH_JWT_* -- never SERVICE_JWT_SECRET, never
    the wrong audience, and never silently when its own secret is unset."""

    def setUp(self):
        self.client = APIClient()
        self.inquiry = inquiry_services.create_inquiry(question="How did Fruition develop?")
        self.snapshot = CorpusSnapshot.objects.create(
            manifest_hash="sha256:y", source_revision_ids=[], captured_at=timezone.now(),
        )
        self.passage = _make_passage("b.md", "Other evidence.")
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
        self.url = reverse("ariadne-inquiry-review-import")

    def _post(self, token):
        return self.client.post(
            self.url, data={"package": self.package}, format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def test_token_signed_with_service_jwt_secret_is_refused(self):
        token = _mint("not-the-ariadne-secret")
        response = self._post(token)
        self.assertIn(response.status_code, (401, 403))

    def test_token_with_wrong_audience_is_refused(self):
        token = _mint("test-ariadne-publish-secret", aud="some-other-service")
        response = self._post(token)
        self.assertIn(response.status_code, (401, 403))

    @override_settings(ARIADNE_ENABLED=True, ARIADNE_PUBLISH_JWT_SECRET=None)
    def test_unset_secret_refuses_every_request_rather_than_falling_back(self):
        # Minted with what *would* be a valid secret if the fallback existed.
        token = _mint("test-ariadne-publish-secret")
        response = self._post(token)
        self.assertIn(response.status_code, (401, 403))

    def test_non_curated_review_returns_400(self):
        token = _mint("test-ariadne-publish-secret")
        bad_package = dict(self.package)
        bad_package["review"] = {**self.package["review"], "status": InquiryReview.Status.DRAFT}
        response = self.client.post(
            self.url, data={"package": bad_package}, format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 400)

    def test_correctly_signed_token_is_accepted(self):
        token = _mint("test-ariadne-publish-secret")
        response = self._post(token)
        self.assertEqual(response.status_code, 201)
