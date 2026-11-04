"""P8: hybrid search + saved searches as Named Lenses.

Vector search is mocked here -- it needs a running Qdrant plus the real
fastembed model, which is exercised separately via
`manage.py ariadne_embed_passages` and a manual search against the real
corpus (see agent-inbox), not in this unit suite. What's tested here: the
merge/dedup logic between lexical and vector hits, concept expansion, and
the saved-search-as-Named-Lens mechanics.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ariadne import search as search_services
from ariadne.models import (
    Concept,
    ConceptAlias,
    Lens,
    Passage,
    SourceDocument,
    SourceRevision,
)

User = get_user_model()


class HybridSearchTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="su", email="su@example.com", password="x")
        document = SourceDocument.objects.create(
            source_system="puddlejump", source_key="decisions/example.md", title="Example",
        )
        revision = SourceRevision.objects.create(
            document=document, content_hash="abc", captured_at=timezone.now(), parser_version="1",
        )
        self.passage = Passage.objects.create(
            revision=revision, ordinal=1, text="Catalyst is the activation layer.", content_hash="def",
        )
        self.other_document = SourceDocument.objects.create(
            source_system="puddlejump", source_key="other.md", title="Other",
        )
        other_revision = SourceRevision.objects.create(
            document=self.other_document, content_hash="xyz", captured_at=timezone.now(), parser_version="1",
        )
        self.other_passage = Passage.objects.create(
            revision=other_revision, ordinal=1, text="Nothing relevant here.", content_hash="uvw",
        )

    @patch("ariadne.search.embed_texts", return_value=[[0.1, 0.2, 0.3]])
    @patch("ariadne.search.get_qdrant_client")
    @patch("ariadne.search.ensure_collection")
    def test_lexical_only_match(self, mock_ensure, mock_get_client, mock_embed):
        mock_client = MagicMock()
        mock_client.query_points.return_value.points = []
        mock_get_client.return_value = mock_client

        results = search_services.hybrid_search("Catalyst")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["passage_id"], str(self.passage.id))
        self.assertEqual(results[0]["found_by"], ["lexical"])

    @patch("ariadne.search.embed_texts", return_value=[[0.1, 0.2, 0.3]])
    @patch("ariadne.search.get_qdrant_client")
    @patch("ariadne.search.ensure_collection")
    def test_vector_hit_merges_with_lexical(self, mock_ensure, mock_get_client, mock_embed):
        hit = MagicMock(id=str(self.other_passage.id), score=0.87)
        mock_client = MagicMock()
        mock_client.query_points.return_value.points = [hit]
        mock_get_client.return_value = mock_client

        results = search_services.hybrid_search("Catalyst")
        by_id = {r["passage_id"]: r for r in results}

        self.assertEqual(by_id[str(self.passage.id)]["found_by"], ["lexical"])
        self.assertEqual(by_id[str(self.other_passage.id)]["found_by"], ["vector"])
        self.assertEqual(by_id[str(self.other_passage.id)]["vector_score"], 0.87)

    @patch("ariadne.search.embed_texts", return_value=[[0.1, 0.2, 0.3]])
    @patch("ariadne.search.get_qdrant_client")
    @patch("ariadne.search.ensure_collection")
    def test_same_passage_found_by_both_methods(self, mock_ensure, mock_get_client, mock_embed):
        hit = MagicMock(id=str(self.passage.id), score=0.95)
        mock_client = MagicMock()
        mock_client.query_points.return_value.points = [hit]
        mock_get_client.return_value = mock_client

        results = search_services.hybrid_search("Catalyst")
        self.assertEqual(len(results), 1)
        self.assertEqual(sorted(results[0]["found_by"]), ["lexical", "vector"])

    @patch("ariadne.search.embed_texts", return_value=[[0.1, 0.2, 0.3]])
    @patch("ariadne.search.get_qdrant_client")
    @patch("ariadne.search.ensure_collection")
    def test_qdrant_failure_degrades_to_lexical_only(self, mock_ensure, mock_get_client, mock_embed):
        mock_get_client.side_effect = ConnectionError("qdrant unreachable")

        results = search_services.hybrid_search("Catalyst")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["found_by"], ["lexical"])

    def test_concept_expansion_widens_lexical_terms(self):
        concept = Concept.objects.create(preferred_label="Catalyst")
        ConceptAlias.objects.create(concept=concept, alias="activation layer")

        with patch("ariadne.search.embed_texts", return_value=[[0.1, 0.2, 0.3]]), patch(
            "ariadne.search.get_qdrant_client"
        ) as mock_get_client, patch("ariadne.search.ensure_collection"):
            mock_get_client.return_value.query_points.return_value.points = []
            results = search_services.hybrid_search("Catalyst")

        self.assertEqual(len(results), 1)
        self.assertIn("concept_expansion_terms", results[0])
        self.assertIn("activation layer", results[0]["concept_expansion_terms"])


class SavedSearchTestCase(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="su2", email="su2@example.com", password="x",
        )

    def test_save_and_list_and_run(self):
        lens_version = search_services.save_search_as_lens(
            name="Fruition coverage", query_text="fruition", owner=self.owner,
        )
        self.assertEqual(lens_version.version, 1)
        self.assertEqual(lens_version.config["kind"], "search")

        saved = list(search_services.list_saved_searches())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].name, "Fruition coverage")

        with patch("ariadne.search.hybrid_search", return_value=[{"passage_id": "x"}]) as mock_search:
            results = search_services.run_saved_search(saved[0])
        mock_search.assert_called_once_with("fruition", limit=search_services.DEFAULT_LIMIT)
        self.assertEqual(results, [{"passage_id": "x"}])

    def test_resaving_same_name_creates_a_new_version(self):
        search_services.save_search_as_lens(name="Fruition coverage", query_text="fruition", owner=self.owner)
        second = search_services.save_search_as_lens(
            name="Fruition coverage", query_text="fruition development", owner=self.owner,
        )
        self.assertEqual(second.version, 2)
        self.assertEqual(Lens.objects.get(name="Fruition coverage").active_version_id, second.id)
