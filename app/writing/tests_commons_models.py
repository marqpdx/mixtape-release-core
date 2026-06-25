from django.contrib.auth import get_user_model
from django.test import TestCase

from files.models import StoredFile
from commons.models import Leaf, LeafEntry


User = get_user_model()


class CommonsLeafModelTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="commons-leaf-author",
            email="commons-leaf@example.com",
            password="testpass123",
        )

    def test_leaf_and_entry_defaults(self):
        leaf = Leaf.objects.create(author=self.author)
        entry = LeafEntry.objects.create(
            leaf=leaf,
            kind=LeafEntry.KIND_TEXT,
            position=1,
        )

        self.assertEqual(leaf.state, Leaf.STATE_OPEN)
        self.assertFalse(leaf.library_only)
        self.assertIsNone(leaf.place)
        self.assertIsNone(leaf.occurred_at)
        self.assertTrue(entry.shared)

    def test_leaf_entry_media_resolves_to_stored_files(self):
        image = StoredFile.objects.create(
            file_path="commons/image.jpg",
            file_name="image.jpg",
            file_type="image/jpeg",
            uploaded_by=self.author,
        )
        audio = StoredFile.objects.create(
            file_path="commons/audio.m4a",
            file_name="audio.m4a",
            file_type="audio/mp4",
            uploaded_by=self.author,
        )
        entry = LeafEntry.objects.create(
            leaf=Leaf.objects.create(author=self.author),
            kind=LeafEntry.KIND_IMAGE,
            position=1,
            image_file=image,
            audio_file=audio,
        )

        entry = LeafEntry.objects.select_related("image_file", "audio_file").get(
            pk=entry.pk
        )
        self.assertEqual(entry.image_file, image)
        self.assertEqual(entry.audio_file, audio)
