# writing/tests/test_docx_import_sponsor.py
#
# POST /api/writing/import/confirm resolves its sponsor the way the batch import
# views do: "user"/"member" find a member, the importer must be allowed to write
# for the sponsor, and the duplicate-file check stays within that sponsor.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from groups.models import Group
from writing.models import WritingPiece

User = get_user_model()
BODY = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Imported."}]}]}


class DocxImportSponsorTests(TestCase):
    def setUp(self):
        self.writer = User.objects.create_user(username="writer", email="writer@example.com", password="testpass123")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="testpass123")
        self.group = Group.objects.create(
            title="Editorial Group", slug="editorial-group", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.writer.pk,
        )
        self.client = APIClient()

    def post(self, user, **extra):
        self.client.force_authenticate(user=user)
        data = {"body_json": BODY, "title": "Imported piece", "file_sha256": "abc123", **extra}
        return self.client.post("/api/writing/import/confirm", data, format="json")

    def test_member_can_import_with_the_user_token(self):
        response = self.post(self.writer, sponsor_type="user", sponsor_id=str(self.writer.pk))
        self.assertEqual(response.status_code, 201, response.content)

    def test_cannot_import_for_another_member(self):
        response = self.post(self.other, sponsor_type="user", sponsor_id=str(self.writer.pk))
        self.assertEqual(response.status_code, 403, response.content)

    def test_cannot_import_for_a_group_without_edit_rights(self):
        response = self.post(self.other, sponsor_type="group", sponsor_id=str(self.group.pk))
        self.assertEqual(response.status_code, 403, response.content)

    def test_duplicate_check_stays_within_the_sponsor(self):
        self.assertEqual(self.post(self.writer, sponsor_type="user", sponsor_id=str(self.writer.pk)).status_code, 201)
        # The same file again for the same sponsor is a duplicate…
        again = self.post(self.writer, sponsor_type="user", sponsor_id=str(self.writer.pk))
        self.assertEqual(again.status_code, 409, again.content)
        # …but another member importing the same file is not blocked or shown it.
        theirs = self.post(self.other, sponsor_type="user", sponsor_id=str(self.other.pk))
        self.assertEqual(theirs.status_code, 201, theirs.content)
        self.assertEqual(WritingPiece.objects.count(), 2)
