# storyboard/tests/test_services.py
#
# Phase 5 acceptance subset (decisions/folio/folio-storyboard-build-handoff.md
# §5, puddlejump): create Parts/Chapters/Scenes against the fiction_v1
# grammar, write Scene prose via the referenced WritingPiece, and
# deliberately reorder siblings. Plus the tree-constraint enforcement the
# acceptance checks can't be satisfied without (build-handoff §3): parent
# validity, cycle prevention, no cross-Storyboard moves.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase

from storyboard.models import Storyboard, StoryboardItem
from storyboard.services import create_item, create_scene, reorder_siblings, reparent_item
from writing.models import WritingPiece

User = get_user_model()


class StoryboardServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="novelist")
        self.user_ct = ContentType.objects.get_for_model(User)
        self.storyboard = Storyboard.objects.create(
            kind="writing",
            grammar="fiction_v1",
            title="Union Station",
            created_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )

    def test_create_part_chapter_scene(self):
        part = create_item(storyboard=self.storyboard, level="part", title="Part I")
        chapter = create_item(
            storyboard=self.storyboard, level="chapter", parent=part, title="Chapter 1"
        )
        scene = create_scene(storyboard=self.storyboard, parent=chapter, title="Arrival")

        self.assertEqual(scene.level, "scene")
        self.assertEqual(scene.parent_id, chapter.id)
        self.assertIsInstance(scene.reference, WritingPiece)
        self.assertEqual(scene.reference.writing_kind, "scene")
        # Authorship and sponsor are inherited from the Storyboard, not the
        # request context (build-handoff §2a).
        self.assertEqual(scene.reference.author_id, self.user.id)
        self.assertEqual(scene.reference.sponsor_content_type_id, self.user_ct.id)
        self.assertEqual(scene.reference.sponsor_object_id, self.user.id)

    def test_chapter_may_be_root_without_a_part(self):
        # Part is optional in practice: None is in chapter's allowed-parent
        # list (build-handoff §3).
        chapter = create_item(storyboard=self.storyboard, level="chapter", title="Prologue")
        self.assertIsNone(chapter.parent)

    def test_scene_cannot_be_a_root_item(self):
        with self.assertRaises(ValidationError):
            create_item(storyboard=self.storyboard, level="scene", title="orphan scene")

    def test_scene_cannot_be_parented_directly_under_part(self):
        part = create_item(storyboard=self.storyboard, level="part", title="Part I")
        with self.assertRaises(ValidationError):
            create_item(storyboard=self.storyboard, level="scene", parent=part, title="bad scene")

    def test_write_actual_scene_prose_via_referenced_writing_piece(self):
        chapter = create_item(storyboard=self.storyboard, level="chapter", title="Chapter 1")
        scene = create_scene(storyboard=self.storyboard, parent=chapter, title="Arrival")

        piece = scene.reference
        piece.body_json = {"type": "doc", "content": [{"type": "paragraph"}]}
        piece.save(update_fields=["body_json", "updated_at"])

        scene.refresh_from_db()
        self.assertEqual(scene.reference.body_json["type"], "doc")

    def test_deliberately_reorder_siblings(self):
        chapter = create_item(storyboard=self.storyboard, level="chapter", title="Chapter 1")
        s1 = create_scene(storyboard=self.storyboard, parent=chapter, title="Morning")
        s2 = create_scene(storyboard=self.storyboard, parent=chapter, title="Noon")
        s3 = create_scene(storyboard=self.storyboard, parent=chapter, title="Night")

        self.assertEqual([s1.rank, s2.rank, s3.rank], [0, 1, 2])

        reorder_siblings(
            storyboard=self.storyboard,
            parent=chapter,
            ordered_item_ids=[s3.id, s1.id, s2.id],
        )

        s1.refresh_from_db()
        s2.refresh_from_db()
        s3.refresh_from_db()
        self.assertEqual(s3.rank, 0)
        self.assertEqual(s1.rank, 1)
        self.assertEqual(s2.rank, 2)

    def test_reparent_rejects_cycle(self):
        part = create_item(storyboard=self.storyboard, level="part", title="Part I")
        chapter = create_item(
            storyboard=self.storyboard, level="chapter", parent=part, title="Chapter 1"
        )
        with self.assertRaises(ValidationError):
            # Moving an ancestor (part) under its own descendant (chapter).
            reparent_item(item=part, new_parent=chapter)

    def test_reparent_rejects_cross_storyboard_move(self):
        chapter = create_item(storyboard=self.storyboard, level="chapter", title="Chapter 1")

        other_storyboard = Storyboard.objects.create(
            kind="writing",
            grammar="fiction_v1",
            title="A Different Book",
            created_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )
        other_part = create_item(storyboard=other_storyboard, level="part", title="Part I")

        with self.assertRaises(ValidationError):
            reparent_item(item=chapter, new_parent=other_part)

    def test_unknown_grammar_key_raises(self):
        bad_storyboard = Storyboard(
            kind="writing",
            grammar="not_a_real_grammar",
            created_by=self.user,
            sponsor_content_type=self.user_ct,
            sponsor_object_id=self.user.id,
        )
        bad_storyboard.save()
        with self.assertRaises(ValueError):
            create_item(storyboard=bad_storyboard, level="part", title="Part I")
