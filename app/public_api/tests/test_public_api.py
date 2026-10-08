from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from classifications.models import Category, ClassificationUsage, Tag
from curation.models import Collection
from groups.services.groups import GroupService
from profiles.models import UserProfile
from publishing.models import ContentPlacement, PublicationGroup
from writing.models import Issue, IssuePlacement, WritingPiece, WritingSynopsis, WritingVersion


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
    sponsor=None,
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
    piece.set_sponsor(sponsor or author)
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
        self.public_collection = _create_collection(
            user=self.author,
            title="Group Writing Feed",
        )
        self.client = APIClient()

    def _url(self) -> str:
        return f"/api/public/groups/{self.group.slug}/writing"

    def _sponsor_with_group(
        self,
        piece: WritingPiece,
        *,
        visibility: str = "public",
    ) -> None:
        piece.set_sponsor(self.group)
        piece.save()
        _create_placement(
            piece=piece,
            target=self.public_collection,
            user=self.author,
            visibility=visibility,
            channel="feed",
        )

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

    def test_group_list_excludes_non_public_placements(self):
        public_piece = _create_piece(author=self.author, title="Public Group Piece")
        self._sponsor_with_group(public_piece)
        unlisted_piece = _create_piece(author=self.author, title="Unlisted Group Piece")
        self._sponsor_with_group(unlisted_piece, visibility="unlisted")
        private_piece = _create_piece(author=self.author, title="Private Group Piece")
        self._sponsor_with_group(private_piece, visibility="private")
        no_placement = _create_piece(
            author=self.author,
            title="Placement-less Group Piece",
        )
        no_placement.set_sponsor(self.group)
        no_placement.save()

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["slug"] for item in response.data], [public_piece.slug])


class PublicGroupIssueViewTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(username="issueauthor", password="testpass123")
        _create_profile(user=self.author, display_name="Issue Author")
        self.group = GroupService.create_group(
            title="Issue Group", group_type="community", created_by=self.author,
            visibility="public", add_creator_membership=False,
        )
        group_ct = ContentType.objects.get_for_model(self.group)
        self.issue = Issue.objects.create(
            title="First Issue", status="published", published_at=timezone.now(),
            sponsor_content_type=group_ct, sponsor_object_id=self.group.pk,
            description=_body_json("Welcome to the issue."),
        )
        self.client = APIClient()

    def _add_piece(self, title, order, *, visibility="public", place=True, status_value="published"):
        piece = _create_piece(
            author=self.author, title=title, sponsor=self.group, status_value=status_value,
        )
        IssuePlacement.objects.create(issue=self.issue, piece=piece, order_index=order)
        if place:
            _create_placement(
                piece=piece, target=self.group, user=self.author,
                visibility=visibility, channel="feed",
            )
        return piece

    def test_lists_only_publicly_placed_pieces_in_issue_order(self):
        second = self._add_piece("Second", 2)
        first = self._add_piece("First", 1)
        self._add_piece("Private", 3, visibility="private")
        self._add_piece("Unplaced", 4, place=False)
        self._add_piece("Draft", 5, status_value="draft")

        url = f"/api/public/groups/{self.group.slug}/writing/issues"
        listing = self.client.get(url)
        detail = self.client.get(f"{url}/{self.issue.slug}")

        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual([p["id"] for p in listing.data[0]["pieces"]], [str(first.pk), str(second.pk)])
        self.assertNotIn("body_json", listing.data[0]["pieces"][0])
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["pieces"][0]["body_json"], first.body_json)

    def test_draft_issue_and_private_group_are_not_public(self):
        self._add_piece("Visible", 0)
        url = f"/api/public/groups/{self.group.slug}/writing/issues"
        self.issue.status = "draft"
        self.issue.save(update_fields=["status"])
        self.assertEqual(self.client.get(url).data, [])
        self.assertEqual(self.client.get(f"{url}/{self.issue.slug}").status_code, 404)

        self.issue.status = "published"
        self.issue.save(update_fields=["status"])
        self.group.visibility = "private"
        self.group.save(update_fields=["visibility"])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(f"{url}/{self.issue.slug}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/public/writing/issues/{self.issue.slug}").status_code, 404)


class PublicMemberWritingViewTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="memberauthor",
            email="memberauthor@example.com",
            password="testpass123",
        )
        _create_profile(user=self.author, display_name="Member Author")
        self.collection = _create_collection(user=self.author, title="Member Feed")
        self.client = APIClient()

    def test_member_list_requires_public_browse_placement(self):
        public_piece = _create_piece(author=self.author, title="Public Member Piece")
        _create_placement(
            piece=public_piece,
            target=self.collection,
            user=self.author,
            visibility="public",
            channel="feed",
        )
        unlisted_piece = _create_piece(
            author=self.author,
            title="Unlisted Member Piece",
        )
        _create_placement(
            piece=unlisted_piece,
            target=self.collection,
            user=self.author,
            visibility="unlisted",
            channel="feed",
        )
        _create_piece(author=self.author, title="Placement-less Member Piece")

        response = self.client.get(
            f"/api/public/members/{self.author.username}/writing"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["slug"] for item in response.data], [public_piece.slug])


class PublicSiteWritingViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="siteowner",
            email="siteowner@example.com",
            password="testpass123",
        )
        self.group_author = User.objects.create_user(
            username="groupwriter",
            email="groupwriter@example.com",
            password="testpass123",
        )
        _create_profile(user=self.owner, display_name="Site Owner")
        _create_profile(user=self.group_author, display_name="Group Writer")
        self.group = GroupService.create_group(
            title="Included Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
            add_creator_membership=False,
        )
        self.other_group = GroupService.create_group(
            title="Excluded Group",
            group_type="community",
            created_by=self.owner,
            visibility="public",
            add_creator_membership=False,
        )
        self.collection = _create_collection(user=self.owner, title="Inside PTSD")
        self.client = APIClient()

    def _url(self, **params) -> str:
        values = {
            "owner": self.owner.username,
            "groups": self.group.slug,
            **params,
        }
        query = "&".join(f"{key}={value}" for key, value in values.items())
        return f"/api/public/sites/writing?{query}"

    def _detail_url(self, piece: WritingPiece, **params) -> str:
        values = {
            "owner": self.owner.username,
            "groups": self.group.slug,
            **params,
        }
        query = "&".join(f"{key}={value}" for key, value in values.items())
        return f"/api/public/sites/writing/{piece.id}?{query}"

    def _place(self, piece: WritingPiece, *, visibility: str = "public") -> None:
        _create_placement(
            piece=piece,
            target=self.collection,
            user=self.owner,
            visibility=visibility,
            channel="feed",
        )

    def _sponsor(self, piece: WritingPiece, group) -> None:
        piece.set_sponsor(group)
        piece.save()

    def test_aggregates_owner_and_group_writing_without_duplicates(self):
        owner_and_group_piece = _create_piece(
            author=self.owner,
            title="Owner and Group",
        )
        self._sponsor(owner_and_group_piece, self.group)
        self._place(owner_and_group_piece)

        group_piece = _create_piece(author=self.group_author, title="Group Piece")
        self._sponsor(group_piece, self.group)
        self._place(group_piece)

        excluded_piece = _create_piece(author=self.group_author, title="Excluded Piece")
        self._sponsor(excluded_piece, self.other_group)
        self._place(excluded_piece)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        returned = {item["slug"]: item for item in response.data["items"]}
        self.assertEqual(set(returned), {owner_and_group_piece.slug, group_piece.slug})
        self.assertEqual(
            set(returned[owner_and_group_piece.slug]["source_keys"]),
            {f"user:{self.owner.username}", f"group:{self.group.slug}"},
        )

    def test_excludes_unlisted_private_members_and_placementless_writing(self):
        public_piece = _create_piece(author=self.owner, title="Public Piece")
        self._place(public_piece)
        for visibility in ("unlisted", "private", "members"):
            piece = _create_piece(
                author=self.owner,
                title=f"{visibility.title()} Piece",
            )
            self._place(piece, visibility=visibility)
        _create_piece(author=self.owner, title="No Placement")

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["items"][0]["slug"], public_piece.slug)

    def test_returns_scoped_taxonomy_collection_tag_and_archive_facets(self):
        piece = _create_piece(author=self.owner, title="Classified Piece")
        self._place(piece)
        piece_ct = ContentType.objects.get_for_model(WritingPiece)

        category = Category(title="Reflections")
        category.sponsor_content_type = ContentType.objects.get_for_model(User)
        category.sponsor_object_id = self.owner.id
        category.save()
        tag = Tag.objects.create(title="Trauma")
        for classification in (category, tag):
            ClassificationUsage.objects.create(
                classification_client_content_type=piece_ct,
                classification_client_object_id=str(piece.id),
                classification_content_type=ContentType.objects.get_for_model(classification.__class__),
                classification_object_id=classification.id,
            )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data["items"][0]
        category_key = f"user:{self.owner.username}:category:{category.slug}"
        collection_key = f"user:{self.owner.username}:collection:{self.collection.slug}"
        self.assertEqual(item["categories"][0]["key"], category_key)
        self.assertEqual(item["collections"][0]["key"], collection_key)
        self.assertEqual(item["tags"][0]["slug"], tag.slug)
        self.assertEqual(response.data["facets"]["categories"][0]["count"], 1)
        self.assertEqual(response.data["facets"]["collections"][0]["count"], 1)
        self.assertEqual(response.data["facets"]["tags"][0]["count"], 1)
        self.assertEqual(
            response.data["facets"]["archives"][0],
            {"year": piece.published_at.year, "count": 1},
        )

    def test_filters_and_paginates_server_side(self):
        first = _create_piece(author=self.owner, title="First Piece")
        first.writing_kind = "article"
        first.save(update_fields=["writing_kind", "updated_at"])
        self._place(first)
        second = _create_piece(author=self.owner, title="Second Piece")
        second.writing_kind = "post"
        second.save(update_fields=["writing_kind", "updated_at"])
        self._place(second)

        filtered = self.client.get(self._url(kind="article"))
        paged = self.client.get(self._url(limit=1, offset=1))

        self.assertEqual(filtered.status_code, status.HTTP_200_OK)
        self.assertEqual(filtered.data["count"], 1)
        self.assertEqual(filtered.data["items"][0]["slug"], first.slug)
        self.assertEqual(paged.status_code, status.HTTP_200_OK)
        self.assertEqual(paged.data["count"], 2)
        self.assertEqual(len(paged.data["items"]), 1)

    def test_requires_owner_and_rejects_missing_group(self):
        missing_owner = self.client.get("/api/public/sites/writing")
        missing_group = self.client.get(self._url(groups="not-a-group"))

        self.assertEqual(missing_owner.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(missing_group.status_code, status.HTTP_404_NOT_FOUND)

    def test_detail_returns_owner_and_group_sponsored_pieces(self):
        owner_piece = _create_piece(author=self.owner, title="Owner Detail")
        self._place(owner_piece)
        group_piece = _create_piece(
            author=self.group_author,
            title="Group Detail",
            sponsor=self.group,
        )
        self._place(group_piece)

        owner_response = self.client.get(self._detail_url(owner_piece))
        group_response = self.client.get(self._detail_url(group_piece))

        self.assertEqual(owner_response.status_code, status.HTTP_200_OK)
        self.assertEqual(owner_response.data["id"], str(owner_piece.id))
        self.assertIsNone(owner_response.data["sponsor_group"])
        self.assertEqual(group_response.status_code, status.HTTP_200_OK)
        self.assertEqual(group_response.data["sponsor_group"]["slug"], self.group.slug)

    def test_detail_rejects_piece_outside_sources_or_public_placements(self):
        excluded_piece = _create_piece(
            author=self.group_author,
            title="Excluded Detail",
            sponsor=self.other_group,
        )
        self._place(excluded_piece)
        unlisted_piece = _create_piece(author=self.owner, title="Unlisted Detail")
        self._place(unlisted_piece, visibility="unlisted")

        excluded_response = self.client.get(self._detail_url(excluded_piece))
        unlisted_response = self.client.get(self._detail_url(unlisted_piece))

        self.assertEqual(excluded_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(unlisted_response.status_code, status.HTTP_404_NOT_FOUND)


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
        self.group = GroupService.create_group(
            title="Reader Group",
            group_type="community",
            created_by=self.author,
            visibility="public",
            add_creator_membership=False,
        )

        self.library = _create_collection(
            user=self.author,
            title="Public Writing",
            visibility="public",
            scope="writing",
        )
        self.client = APIClient()

    def _url(self, slug: str) -> str:
        return f"/api/public/groups/{self.group.slug}/writing/{slug}"

    def _piece(self, **kwargs) -> WritingPiece:
        return _create_piece(author=self.author, sponsor=self.group, **kwargs)

    def test_get_piece_anonymous_public_placement(self):
        piece = self._piece(title="Readable Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in ["title", "body_json", "author", "slug", "published_at"]:
            self.assertIn(key, response.data)

    def test_get_piece_no_email_in_author(self):
        piece = self._piece(title="Author Shape Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data["author"].keys()), {"username", "display_name", "avatar_url"})

    def test_get_piece_draft_returns_404(self):
        piece = self._piece(title="Draft", status_value="draft")
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_no_visible_placement_returns_404(self):
        piece = self._piece(title="No Placement")
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_private_placement_anonymous(self):
        piece = self._piece(title="Private Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="private")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_members_placement_authenticated(self):
        piece = self._piece(title="Members Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="members")

        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["placement_visibility"], "members")

    def test_get_piece_nonexistent_slug(self):
        response = self.client.get(self._url("missing-piece"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_rejects_piece_from_another_group(self):
        other_group = GroupService.create_group(
            title="Other Reader Group",
            group_type="community",
            created_by=self.author,
            visibility="public",
            add_creator_membership=False,
        )
        piece = _create_piece(author=self.author, sponsor=other_group, title="Other Group Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_piece_exposes_only_confirmed_public_synopsis(self):
        piece = self._piece(title="Preview Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")
        synopsis = WritingSynopsis.objects.create(
            piece=piece,
            description="A deliberate preview description.",
        )

        unconfirmed = self.client.get(self._url(piece.slug))
        self.assertEqual(unconfirmed.data["public_synopsis"], "")

        synopsis.public_synopsis_confirmed = True
        synopsis.save(update_fields=["public_synopsis_confirmed", "updated_at"])
        confirmed = self.client.get(self._url(piece.slug))
        self.assertEqual(confirmed.data["public_synopsis"], "A deliberate preview description.")

    def test_get_piece_increments_view_count(self):
        piece = self._piece(title="Counted Piece")
        _create_placement(piece=piece, target=self.library, user=self.author, visibility="public")

        before = piece.view_count
        response = self.client.get(self._url(piece.slug))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        piece.refresh_from_db()
        self.assertEqual(piece.view_count, before + 1)

    def test_get_piece_applies_overrides(self):
        piece = self._piece(title="Original Title", excerpt="Original excerpt")
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
