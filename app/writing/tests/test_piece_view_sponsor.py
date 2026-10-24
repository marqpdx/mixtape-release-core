# writing/tests/test_piece_view_sponsor.py
#
# The piece detail (GET /api/writing/pieces/view/<slug>) says where a piece
# lives, so the /app/writing/<slug> permalink can send a reader to its home.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from groups.models import Group
from writing.api.serializers import WritingPieceDetailSerializer
from writing.models import WritingPiece

User = get_user_model()
BODY = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello."}]}]}


class PieceDetailSponsorFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="writer", email="writer@example.com", password="testpass123")
        self.group = Group.objects.create(
            title="Editorial Group", slug="editorial-group", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user.pk,
        )

    def data(self, sponsor, title):
        piece = WritingPiece(author=self.user, title=title, body_json=BODY, status="published", published_at=timezone.now())
        piece.set_sponsor(sponsor)
        piece.set_submitted_by(self.user)
        piece.save()
        return WritingPieceDetailSerializer(piece).data

    def test_member_piece(self):
        data = self.data(self.user, "Member piece")
        self.assertEqual(data["sponsor_type"], "member")
        self.assertEqual(data["sponsor_slug"], "writer")
        self.assertEqual(data["author_username"], "writer")

    def test_group_piece(self):
        data = self.data(self.group, "Group piece")
        self.assertEqual(data["sponsor_type"], "group")
        self.assertEqual(data["sponsor_slug"], "editorial-group")
        self.assertEqual(data["sponsor_name"], "Editorial Group")
