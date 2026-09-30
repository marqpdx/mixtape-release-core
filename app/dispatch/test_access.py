import base64
import hashlib
import time

import jwt
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from dispatch.access import can_access_dispatch_content
from dispatch.models import DispatchCollaborator, DispatchContent
from groups.models import Group, GroupMembership
from livewire.api.views import _mint_service_token
from writing.models import WorkingDocument, WritingPiece


User = get_user_model()


@override_settings(
    SERVICE_JWT_SECRET="dispatch-access-test-secret",
    LIVEWIRE_JWT_SECRET="dispatch-persist-test-secret",
)
class DispatchDraftAccessTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="dispatch_author", password="testpass123")
        self.editor = User.objects.create_user(username="dispatch_editor", password="testpass123")
        self.commenter = User.objects.create_user(username="dispatch_commenter", password="testpass123")
        self.stranger = User.objects.create_user(username="dispatch_stranger", password="testpass123")
        self.group = Group.objects.create(
            title="Dispatch Access", slug="dispatch-access", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.author.pk,
        )
        user_type = ContentType.objects.get_for_model(User)
        self.memberships = {}
        for user in (self.author, self.editor, self.commenter):
            self.memberships[user.pk] = GroupMembership.objects.create(
                group=self.group, member_content_type=user_type,
                member_object_id=user.pk, roles=["member"],
                is_active=True, is_pending=False,
            )
        self.piece = WritingPiece(
            author=self.author, author_name=self.author.username,
            title="Shared Draft", body_json={"type": "doc", "content": []}, status="draft",
        )
        self.piece.set_sponsor(self.group)
        self.piece.set_submitted_by(self.author)
        self.piece.save()
        self.content = DispatchContent.objects.create(created_by=self.author)
        WorkingDocument.objects.create(
            piece=self.piece, user=self.author, dispatch_content=self.content,
            body_json={"type": "doc", "content": []},
        )
        for user, role in ((self.author, "editor"), (self.editor, "editor"), (self.commenter, "commenter")):
            DispatchCollaborator.objects.create(content=self.content, user=user, role=role)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def service_client_for(self, user):
        token = _mint_service_token(str(user.pk), ["dispatch:write"])["service_token"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_active_editor_and_commenter_permissions(self):
        self.assertTrue(can_access_dispatch_content(self.author, self.content, write=True))
        self.assertTrue(can_access_dispatch_content(self.editor, self.content, write=True))
        self.assertTrue(can_access_dispatch_content(self.commenter, self.content))
        self.assertFalse(can_access_dispatch_content(self.commenter, self.content, write=True))
        self.assertFalse(can_access_dispatch_content(self.stranger, self.content))

        state_url = f"/api/dispatch/content/{self.content.pk}/yjs-state"
        self.assertEqual(self.client_for(self.commenter).get(state_url).status_code, 200)
        self.assertEqual(self.client_for(self.commenter).patch(
            state_url, {"yjs_state": base64.b64encode(b"not-an-edit").decode("ascii")}, format="json"
        ).status_code, 404)

        url = f"/api/dispatch/content/{self.content.pk}/authorize-room"
        payload = {"document_id": str(self.content.yjs_document_id), "action": "read"}
        self.assertEqual(self.service_client_for(self.commenter).post(url, payload).status_code, 200)
        self.assertEqual(self.service_client_for(self.commenter).post(
            url, {**payload, "action": "write"}
        ).status_code, 403)
        self.assertEqual(self.service_client_for(self.editor).post(
            url, {**payload, "action": "write"}
        ).status_code, 200)
        self.assertEqual(self.service_client_for(self.editor).post(
            url, {**payload, "document_id": str(self.piece.pk)}
        ).status_code, 404)

    def test_revoked_author_and_editor_lose_draft_and_room_access(self):
        for user in (self.author, self.editor):
            self.memberships[user.pk].is_active = False
            self.memberships[user.pk].save(update_fields=["is_active"])
            self.assertFalse(can_access_dispatch_content(user, self.content))
            self.assertEqual(self.client_for(user).get(f"/api/dispatch/content/{self.content.pk}").status_code, 404)
            self.assertEqual(self.client_for(user).get(
                f"/api/dispatch/content/{self.content.pk}/yjs-state"
            ).status_code, 404)
            self.assertEqual(self.client_for(user).get(f"/api/writing/pieces/{self.piece.pk}").status_code, 403)
            self.assertEqual(self.service_client_for(user).post(
                f"/api/dispatch/content/{self.content.pk}/authorize-room",
                {"document_id": str(self.content.yjs_document_id), "action": "read"},
            ).status_code, 403)

        drafts = self.client_for(self.author).get(
            f"/api/writing/drafts?sponsor_type=group&sponsor_slug={self.group.slug}&filter=all"
        )
        self.assertEqual(drafts.status_code, 200)
        self.assertEqual(len(drafts.data), 0)
        pieces = self.client_for(self.author).get("/api/writing/pieces?status=draft")
        self.assertEqual(pieces.status_code, 200)
        self.assertNotIn(str(self.piece.pk), str(pieces.data))

    def test_only_signed_livewire_flush_can_persist_an_accepted_pre_revocation_update(self):
        self.memberships[self.author.pk].is_active = False
        self.memberships[self.author.pk].save(update_fields=["is_active"])
        state = b"accepted-before-revocation"
        encoded = base64.b64encode(state).decode("ascii")
        url = f"/api/dispatch/content/{self.content.pk}/yjs-state"
        ordinary = self.service_client_for(self.author)
        self.assertEqual(ordinary.patch(url, {"yjs_state": encoded}, format="json").status_code, 404)

        proof = jwt.encode({
            "content_id": str(self.content.pk),
            "document_id": str(self.content.yjs_document_id),
            "state_sha256": hashlib.sha256(state).hexdigest(),
            "scope": "dispatch:persist",
        }, settings.LIVEWIRE_JWT_SECRET, algorithm="HS256")
        # A bare token without the required issuer/audience/expiry is not a persistence proof.
        token = _mint_service_token(str(self.author.pk), ["dispatch:write"])["service_token"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_LIVEWIRE_PERSIST=proof)
        self.assertEqual(client.patch(url, {"yjs_state": encoded}, format="json").status_code, 404)

        now = int(time.time())
        proof = jwt.encode({
            "content_id": str(self.content.pk),
            "document_id": str(self.content.yjs_document_id),
            "state_sha256": hashlib.sha256(state).hexdigest(),
            "scope": "dispatch:persist",
            "iat": now, "exp": now + 15,
            "iss": "livewire-persist", "aud": "django-dispatch",
        }, settings.LIVEWIRE_JWT_SECRET, algorithm="HS256")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_LIVEWIRE_PERSIST=proof)
        self.assertEqual(client.patch(url, {"yjs_state": encoded}, format="json").status_code, 200)
        self.content.refresh_from_db()
        self.assertEqual(bytes(self.content.yjs_state), state)
