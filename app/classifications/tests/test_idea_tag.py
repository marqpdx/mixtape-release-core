from unittest.mock import patch

from django.test import TestCase

from classifications.models import Tag
from inkwell.stackroom_adapters import get_adapter
from inkwell.stackroom_adapters.tag import TagAdapter


class TagIsIdeaTests(TestCase):
    def test_is_idea_defaults_false(self):
        tag = Tag.objects.create(title="Singing together")
        self.assertFalse(tag.is_idea)

    def test_is_idea_can_be_set(self):
        tag = Tag.objects.create(title="Gathering", is_idea=True)
        self.assertTrue(tag.is_idea)


class TagStackroomSignalTests(TestCase):
    @patch("inkwell.stackroom_enqueue.enqueue_stackroom_ingest")
    def test_ordinary_tag_save_does_not_enqueue(self, mock_enqueue):
        Tag.objects.create(title="just a tag")
        mock_enqueue.assert_not_called()

    @patch("inkwell.stackroom_enqueue.enqueue_stackroom_ingest")
    def test_idea_tag_save_enqueues_ingest(self, mock_enqueue):
        tag = Tag.objects.create(title="Singing together", is_idea=True)
        mock_enqueue.assert_called_once_with(tag, reason="tag_idea_save")

    @patch("inkwell.stackroom_enqueue.enqueue_stackroom_ingest")
    def test_idea_tag_resave_enqueues_again(self, mock_enqueue):
        tag = Tag.objects.create(title="Singing together", is_idea=True)
        mock_enqueue.reset_mock()
        tag.summary = "Strangers singing in harmony"
        tag.save()
        mock_enqueue.assert_called_once_with(tag, reason="tag_idea_save")


class TagAdapterTests(TestCase):
    def test_get_adapter_resolves_idea_tag_to_tag_adapter(self):
        tag = Tag.objects.create(title="Gathering", is_idea=True)
        self.assertIsInstance(get_adapter(tag), TagAdapter)

    def test_get_adapter_raises_for_ordinary_tag(self):
        tag = Tag.objects.create(title="just a tag")
        with self.assertRaises(ValueError):
            get_adapter(tag)

    def test_build_text_includes_title_and_summary(self):
        tag = Tag(title="Singing together", summary="Strangers in harmony", is_idea=True)
        text = TagAdapter().build_text(tag)
        self.assertIn("Singing together", text)
        self.assertIn("Strangers in harmony", text)

    def test_build_text_without_summary(self):
        tag = Tag(title="Gathering", is_idea=True)
        text = TagAdapter().build_text(tag)
        self.assertEqual(text, "Gathering")
