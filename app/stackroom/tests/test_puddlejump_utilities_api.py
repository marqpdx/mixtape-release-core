from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from stackroom.models import Library


User = get_user_model()


def _create_library(*, user: User, title: str, visibility: str = "public") -> Library:
    library = Library(
        title=title,
        summary="Test summary",
        body="Test body",
        scope="writing",
        visibility=visibility,
    )
    library.set_sponsor(user)
    library.set_submitted_by(user)
    library.author = user
    library.author_name = user.get_full_name() or user.username
    library.save()
    return library


class PuddlejumpUtilitiesAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="pj_user",
            email="pj_user@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="pj_other",
            email="pj_other@example.com",
            password="testpass123",
        )
        self.library = _create_library(user=self.user, title="My Library")
        self.other_library = _create_library(user=self.other_user, title="Other Library")

    def _auth(self):
        self.client.force_authenticate(user=self.user)

    def test_health_requires_auth(self):
        response = self.client.get(
            f"/api/stackroom/puddlejump/utilities/libraries/{self.library.id}/health"
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    @mock.patch("stackroom.api.puddlejump_utility_views.get_library_health")
    def test_health_ok(self, mock_health):
        self._auth()
        mock_health.return_value = {
            "library_id": str(self.library.id),
            "file_count": 0,
            "total_size_bytes": 0,
            "folder_depth": 0,
            "canon_coverage": {"total_items": 0, "canonical_items": 0, "percentage": 0},
            "summary_coverage": {"total_artifacts": 0, "with_summary": 0, "percentage": 0},
            "keyword_coverage": {"total_artifacts": 0, "with_keywords": 0, "percentage": 0},
            "missing_summaries": [],
            "overdue_reviews": [],
            "ingestion_status": {
                "total_source_files": 0,
                "fully_embedded": 0,
                "pending_embedding": 0,
                "failed_embedding": 0,
                "percentage_complete": 0,
            },
        }

        response = self.client.get(
            f"/api/stackroom/puddlejump/utilities/libraries/{self.library.id}/health"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["library_id"], str(self.library.id))
        self.assertIn("canon_coverage", response.data)
        self.assertIn("summary_coverage", response.data)
        self.assertIn("keyword_coverage", response.data)
        self.assertIn("ingestion_status", response.data)

    def test_health_access_denied(self):
        self._auth()
        response = self.client.get(
            f"/api/stackroom/puddlejump/utilities/libraries/{self.other_library.id}/health"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get("error"), "Library not found or access denied")

    def test_missing_library_id(self):
        self._auth()
        for path in (
            "/api/stackroom/puddlejump/utilities/check-duplicates",
            "/api/stackroom/puddlejump/utilities/extract-glossary",
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            "/api/stackroom/puddlejump/utilities/suggest-summaries",
            "/api/stackroom/puddlejump/utilities/restructure",
        ):
            response = self.client.post(path, {}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data.get("error"), "library_id is required")

    @mock.patch("stackroom.api.puddlejump_utility_views.detect_duplicates")
    def test_duplicate_detection_default_threshold(self, mock_detect):
        self._auth()
        mock_detect.return_value = [
            {
                "source_file_a_id": "a",
                "filename_a": "a.md",
                "source_file_b_id": "b",
                "filename_b": "b.md",
                "similarity_score": 0.9,
                "excerpt_a": "a",
                "excerpt_b": "b",
            }
        ]

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/check-duplicates",
            {"library_id": str(self.library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["similarity_threshold"], 0.85)
        self.assertEqual(response.data["pair_count"], 1)

    @mock.patch("stackroom.api.puddlejump_utility_views.detect_duplicates")
    def test_duplicate_detection_custom_threshold(self, mock_detect):
        self._auth()
        mock_detect.return_value = []

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/check-duplicates",
            {"library_id": str(self.library.id), "similarity_threshold": 0.7},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["similarity_threshold"], 0.7)

    def test_duplicate_detection_invalid_threshold(self):
        self._auth()
        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/check-duplicates",
            {"library_id": str(self.library.id), "similarity_threshold": 1.5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data.get("error"),
            "similarity_threshold must be a number between 0 and 1",
        )

    @mock.patch("stackroom.api.puddlejump_utility_views.extract_glossary")
    def test_glossary_default_min_occurrences(self, mock_extract):
        self._auth()
        mock_extract.return_value = [
            {
                "term": "Example",
                "definition": "Example definition",
                "source_files": [],
                "occurrences": 1,
            }
        ]

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/extract-glossary",
            {"library_id": str(self.library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["min_occurrences"], 1)
        self.assertEqual(response.data["term_count"], 1)

    @mock.patch("stackroom.api.puddlejump_utility_views.extract_glossary")
    def test_glossary_min_occurrences(self, mock_extract):
        self._auth()
        mock_extract.return_value = []

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/extract-glossary",
            {"library_id": str(self.library.id), "min_occurrences": 3},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["min_occurrences"], 3)

    def test_glossary_invalid_min_occurrences(self):
        self._auth()
        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/extract-glossary",
            {"library_id": str(self.library.id), "min_occurrences": 0},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("error"), "min_occurrences must be a positive integer")

    @mock.patch("stackroom.api.puddlejump_utility_views.suggest_canonical_candidates")
    def test_canonical_candidates_default(self, mock_suggest):
        self._auth()
        mock_suggest.return_value = [
            {
                "source_file_id": "a",
                "filename": "a.md",
                "score": 0.9,
                "reasons": ["Referenced by 2 other documents"],
                "is_canonical": False,
                "library_item_id": "",
            }
        ]

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            {"library_id": str(self.library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["top_n"], 10)
        self.assertEqual(response.data["candidate_count"], 1)

    @mock.patch("stackroom.api.puddlejump_utility_views.suggest_canonical_candidates")
    def test_canonical_candidates_exclude(self, mock_suggest):
        self._auth()
        mock_suggest.return_value = []

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            {
                "library_id": str(self.library.id),
                "exclude_already_canonical": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["exclude_already_canonical"])

    @mock.patch("stackroom.api.puddlejump_utility_views.suggest_canonical_candidates")
    def test_canonical_candidates_top_n(self, mock_suggest):
        self._auth()
        mock_suggest.return_value = []

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            {"library_id": str(self.library.id), "top_n": 3},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["top_n"], 3)

    def test_post_access_denied(self):
        self._auth()
        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/check-duplicates",
            {"library_id": str(self.other_library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get("error"), "Library not found or access denied")

    def test_post_requires_auth(self):
        for path in (
            "/api/stackroom/puddlejump/utilities/check-duplicates",
            "/api/stackroom/puddlejump/utilities/extract-glossary",
            "/api/stackroom/puddlejump/utilities/suggest-canonical",
            "/api/stackroom/puddlejump/utilities/suggest-summaries",
            "/api/stackroom/puddlejump/utilities/restructure",
        ):
            response = self.client.post(path, {"library_id": str(self.library.id)}, format="json")
            self.assertIn(
                response.status_code,
                (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
            )

    @mock.patch("stackroom.api.puddlejump_utility_views.suggest_summaries")
    def test_suggest_summaries_default(self, mock_suggest):
        self._auth()
        mock_suggest.return_value = [
            {
                "artifact_id": "a",
                "source_file_id": "b",
                "filename": "a.md",
                "suggested_summary": "Summary",
                "method": "llm_abstractive",
                "error": None,
            }
        ]

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-summaries",
            {"library_id": str(self.library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_missing"], 1)
        self.assertEqual(response.data["suggestions_generated"], 1)
        self.assertEqual(len(response.data["suggestions"]), 1)

    def test_suggest_summaries_access_denied(self):
        self._auth()
        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/suggest-summaries",
            {"library_id": str(self.other_library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get("error"), "Library not found or access denied")

    @mock.patch("stackroom.api.puddlejump_utility_views.restructure_documents")
    def test_restructure_default(self, mock_restructure):
        self._auth()
        mock_restructure.return_value = [
            {
                "cluster_id": 0,
                "documents": [
                    {"source_file_id": "a", "filename": "a.md", "excerpt": "a"},
                    {"source_file_id": "b", "filename": "b.md", "excerpt": "b"},
                ],
                "document_count": 2,
                "similarity_avg": 0.7,
                "outline": "",
                "outline_method": "none",
            }
        ]

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/restructure",
            {"library_id": str(self.library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["similarity_threshold"], 0.6)
        self.assertEqual(response.data["cluster_count"], 1)

    @mock.patch("stackroom.api.puddlejump_utility_views.restructure_documents")
    def test_restructure_custom_threshold(self, mock_restructure):
        self._auth()
        mock_restructure.return_value = []

        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/restructure",
            {"library_id": str(self.library.id), "similarity_threshold": 0.8},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["similarity_threshold"], 0.8)

    def test_restructure_invalid_threshold(self):
        self._auth()
        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/restructure",
            {"library_id": str(self.library.id), "similarity_threshold": 1.5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data.get("error"),
            "similarity_threshold must be a number between 0 and 1",
        )

    def test_restructure_access_denied(self):
        self._auth()
        response = self.client.post(
            "/api/stackroom/puddlejump/utilities/restructure",
            {"library_id": str(self.other_library.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data.get("error"), "Library not found or access denied")
