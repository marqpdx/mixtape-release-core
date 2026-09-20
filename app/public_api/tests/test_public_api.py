from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from profiles.models import UserProfile
from publishing.models import ContentPlacement, PublicationGroup
from curation.models import Collection
from groups.services.groups import GroupService
from writing.models import WritingPiece, WritingVersion


User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _create_profile(*, user: User, display_name: str = "Test User") -> UserProfile:
    return UserProfile.objects.create(
        user=user,
        slug="",
        display_name=display_name,
        quick_intro="I write things",
        avatar_url="https://example.com/avatar.png",
    )


def _create_collection(
    *,
    user: User,
    title: str,
    visibility: str = "public",
    scope: str = "writing",
) -> Collection:
    collection = Collection(
        title=title,
        summary=f"Summary for {title}",
        visibility=visibility,
        scope=scope,
        author=user,
        author_name=user.username,
    )
    collection.set_sponsor(user)
    collection.set_submitted_by(user)
    collection.save()
    return collection


def _create_piece(
    *,
    author: User,
    title: str,
    status_value: str = "published",
    excerpt: str = "Excerpt",
) -> WritingPiece:
    piece = WritingPiece(
        author=author,
        author_name=author.username,
        title=title,
        excerpt=excerpt,
        body_json=_body_json(f"Body for {title}"),
        status=status_value,
        writing_kind="article",
    )
    piece.set_sponsor(author)
    piece.set_submitted_by(author)
    if status_value == "published":
        piece.published_at = timezone.now()
    piece.save()

    if status_value in {"published", "archived"}:
        WritingVersion.objects.create(
            writing_piece=piece,
            sequence_no=1,
            version_label="1",
            body_json=piece.body_json,
            title=piece.title,
            excerpt=piece.excerpt,
            kind="release",
            created_by=author,
        )
    return piece


def _create_pub_group(*, piece: WritingPiece, user: User) -> PublicationGroup:
    ct_piece = ContentType.objects.get_for_model(WritingPiece)
    return PublicationGroup.objects.create(
        created_by=user,
        source_content_type=ct_piece,
        source_object_id=piece.id,
    )


def _create_placement(
    *,
    piece: WritingPiece,
    target,
    user: User,
    visibility: str,
    channel: str = "shelf",
    follow_updates: bool = True,
    order_index: int = 0,
    overrides: dict | None = None,
) -> ContentPlacement:
    ct_piece = ContentType.objects.get_for_model(WritingPiece)
    ct_target = ContentType.objects.get_for_model(target.__class__)
    return ContentPlacement.objects.create(
        publication_group=_create_pub_group(piece=piece, user=user),
        placed_by=user,
        source_content_type=ct_piece,
        source_object_id=piece.id,
        target_content_type=ct_target,
        target_object_id=target.id,
        channel=channel,
        visibility=visibility,
        follow_updates=follow_updates,
        order_index=order_index,
        overrides=overrides or {},
    )


class PublicMemberProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="testpass123",
        )
        self.profile = _create_profile(user=self.user, display_name="Test User")
        self.client = APIClient()

    def _url(self, username: str) -> str:
        return f"/api/public/members/{username}"

    def test_get_profile_anonymous(self):
        response = self.client.get(self._url(self.user.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        for key in ["display_name", "username", "quick_intro", "avatar_url", "date_joined"]:
            self.assertIn(key, data)
        self.assertEqual(data["username"], self.user.username)
        self.assertEqual(data["display_name"], self.profile.display_name)

    def test_get_profile_authenticated(self):
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self._url(self.user.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], self.user.username)

    def test_get_profile_no_email_no_roles(self):
        response = self.client.get(self._url(self.user.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        forbidden = {"email", "roles", "is_active", "first_name", "last_name"}
        self.assertTrue(forbidden.isdisjoint(set(response.data.keys())))

    def test_get_profile_nonexistent_user(self):
        response = self.client.get(self._url("does-not-exist"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_profile_inactive_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.client.get(self._url(self.user.username))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_profile_soft_deleted(self):
        self.profile.deleted_at = timezone.now()
        self.profile.save(update_fields=["deleted_at"])
        response = self.client.get(self._url(self.user.username))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class PublicMemberShelvesViewTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="testpass123",
        )
        _create_profile(user=self.author, display_name="Author")

        self.public_collection = _create_collection(
            user=self.author,
            title="Public Writing",
            visibility="public",
            scope="writing",
        )
        self.members_collection = _create_collection(
            user=self.author,
            title="Members Writing",
            visibility="members",
            scope="writing",
        )
        self.private_collection = _create_collection(
            user=self.author,
            title="Private Writing",
            visibility="private",
            scope="writing",
        )
        self.unlisted_collection = _create_collection(
            user=self.author,
            title="Unlisted Writing",
            visibility="unlisted",
            scope="writing",
        )
        self.general_collection = _create_collection(
            user=self.author,
            title="General Library",
            visibility="public",
            scope="general",
        )

        self.public_piece = _create_piece(author=self.author, title="Published Public")
        _create_placement(
            piece=self.public_piece,
            target=self.public_collection,
            user=self.author,
            visibility="public",
        )

        self.members_piece = _create_piece(author=self.author, title="Published Members")
        _create_placement(
            piece=self.members_piece,
            target=self.public_collection,
            user=self.author,
            visibility="members",
            order_index=1,
        )

        self.private_piece = _create_piece(author=self.author, title="Published Private")
        _create_placement(
            piece=self.private_piece,
            target=self.public_collection,
            user=self.author,
            visibility="private",
            order_index=2,
        )

        self.draft_piece = _create_piece(
            author=self.author,
            title="Draft Piece",
            status_value="draft",
        )
        _create_placement(
            piece=self.draft_piece,
            target=self.public_collection,
            user=self.author,
            visibility="public",
            order_index=3,
        )

        self.archived_piece = _create_piece(
            author=self.author,
            title="Archived Piece",
            status_value="archived",
        )
        _create_placement(
            piece=self.archived_piece,
            target=self.public_collection,
            user=self.author,
            visibility="public",
            order_index=4,
        )

        self.members_collection_piece = _create_piece(author=self.author, title="Members Shelf Piece")
        _create_placement(
            piece=self.members_collection_piece,
            target=self.members_collection,
            user=self.author,
            visibility="members",
        )

        self.client = APIClient()

    def _url(self, username: str) -> str:
        return f"/api/public/members/{username}/shelves"

    def test_shelves_anonymous_sees_public_only(self):
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["visibility"], "public")

    def test_shelves_authenticated_sees_public_and_members(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        visibilities = {row["visibility"] for row in response.data}
        self.assertEqual(visibilities, {"public", "members"})

    def test_shelves_excludes_private_and_unlisted(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {row["id"] for row in response.data}
        self.assertNotIn(str(self.private_collection.id), returned_ids)
        self.assertNotIn(str(self.unlisted_collection.id), returned_ids)

    def test_shelves_only_writing_scope(self):
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {row["id"] for row in response.data}
        self.assertNotIn(str(self.general_collection.id), returned_ids)

    def test_shelves_items_inline(self):
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.data[0]["items"]
        self.assertGreaterEqual(len(items), 1)
        expected_keys = {"id", "title", "slug", "excerpt", "writing_kind", "published_at"}
        self.assertTrue(expected_keys.issubset(set(items[0].keys())))

    def test_shelves_items_only_published_pieces(self):
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [item["slug"] for item in response.data[0]["items"]]
        self.assertIn(self.public_piece.slug, slugs)
        self.assertNotIn(self.draft_piece.slug, slugs)
        self.assertNotIn(self.archived_piece.slug, slugs)

    def test_shelves_items_respect_placement_visibility(self):
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [item["slug"] for item in response.data[0]["items"]]
        self.assertIn(self.public_piece.slug, slugs)
        self.assertNotIn(self.members_piece.slug, slugs)
        self.assertNotIn(self.private_piece.slug, slugs)

    def test_shelves_nonexistent_user(self):
        response = self.client.get(self._url("does-not-exist"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_shelves_empty_when_no_libraries(self):
        empty_user = User.objects.create_user(
            username="nolibs",
            email="nolibs@example.com",
            password="testpass123",
        )
        response = self.client.get(self._url(empty_user.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_shelves_item_count_matches_items(self):
        response = self.client.get(self._url(self.author.username))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for shelf in response.data:
            self.assertEqual(shelf["item_count"], len(shelf["items"]))


class PublicGroupWritingViewTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="groupauthor",
            email="groupauthor@example.com",
            password="testpass123",
        )
        _create_profile(user=self.author, display_name="Group Author")
        self.group = GroupService.create_group(
            title="Public Writing Group",
            group_type="community",
            created_by=self.author,
            visibility="public",
            add_creator_membership=False,
        )
        self.client = APIClient()

    def _url(self) -> str:
        return f"/api/public/groups/{self.group.slug}/writing"

    def _sponsor_with_group(self, piece: WritingPiece) -> None:
        piece.set_sponsor(self.group)
        piece.save()

    def test_body_preview_is_derived_from_published_body(self):
        piece = _create_piece(
            author=self.author,
            title="Body Preview Piece",
            excerpt="Canonical excerpt stays separate.",
        )
        piece.body_json = _body_json("Actual opening sentence. More body follows.")
        self._sponsor_with_group(piece)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["body_preview"], "Actual opening sentence. More body follows.")
        self.assertEqual(response.data[0]["excerpt"], "Canonical excerpt stays separate.")

    def test_body_preview_falls_back_to_excerpt_when_body_is_empty(self):
        piece = _create_piece(
            author=self.author,
            title="Excerpt Fallback Piece",
            excerpt="Fallback excerpt sentence.",
        )
        piece.body_json = {}
        self._sponsor_with_group(piece)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["body_preview"], "Fallback excerpt sentence.")


class PublicWritingPieceViewTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="testpass123",
        )
        _create_profile(user=self.author, display_name="Author Name")

        self.library = _create_collection(
            user=self.author,
            title="Public Writing",
            visibility="public",
            scope="writing",
        )
        self.client = APIClient()

    def _url(self, slug: str) -> str:
        return f"/api/public/writing/{slug}"

    def test_get_piece_anonymous_public_placement(self):
        piece = _create_piece(author=self.author, title="Readable Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in ["title", "body_json", "author", "slug", "published_at"]:
            self.assertIn(key, response.data)

    def test_get_piece_no_email_in_author(self):
        piece = _create_piece(author=self.author, title="Author Shape Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data["author"].keys()), {"username", "display_name", "avatar_url"})

    def test_get_piece_draft_returns_404(self):
        piece = _create_piece(author=self.author, title="Draft", status_value="draft")
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_no_visible_placement_returns_404(self):
        piece = _create_piece(author=self.author, title="No Placement")
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_private_placement_anonymous(self):
        piece = _create_piece(author=self.author, title="Private Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="private")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_members_placement_authenticated(self):
        piece = _create_piece(author=self.author, title="Members Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="members")

        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["placement_visibility"], "members")

    def test_get_piece_nonexistent_slug(self):
        response = self.client.get(self._url("missing-piece"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_increments_view_count(self):
        piece = _create_piece(author=self.author, title="Counted Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        before = piece.view_count
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        piece.refresh_from_db()
        self.assertEqual(piece.view_count, before + 1)

    def test_get_piece_applies_overrides(self):
        piece = _create_piece(author=self.author, title="Original Title", excerpt="Original excerpt")
        _create_placement(
            piece=piece,
            target=self.library,
            user=self.author,
            visibility="public",
            overrides={
                "title": "Override Title",
                "excerpt": "Override excerpt",
            },
        )

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Override Title")
        self.assertEqual(response.data["excerpt"], "Override excerpt")
