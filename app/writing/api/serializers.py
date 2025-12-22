# api/writing/serializers.py

from django.contrib.auth import get_user_model
from rest_framework import serializers

from utils.shared.contenttypes import resolve_content_type
from writing.choices import ContentStatus

from ..models import (
    Seed,
    WritingComment,
    WritingPiece,
    WritingPlacement,
    WritingVersion,
    WritingWorkingCopy,
)


User = get_user_model()

class WritingPieceSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(
        choices=ContentStatus.choices,
        default=ContentStatus.DRAFT,
        required=False,
    )
    slug = serializers.CharField(read_only=True)
    title = serializers.CharField(allow_blank=True, required=False, default="")
    sponsor_content_type = serializers.CharField(write_only=True)
    sponsor_object_id = serializers.UUIDField()

    create_working_copy = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = WritingPiece
        fields = "__all__"
        read_only_fields = (
            "slug",
            "author",
            "current_version_no",
            "view_count",
            "comment_count",
            "published_at",
        )

    def validate(self, attrs):
        data = super().validate(attrs)
        raw_ct = self.initial_data.get("sponsor_content_type")
        if not raw_ct:
            raise serializers.ValidationError({"sponsor": "Sponsor is required (content_type + object_id)."})

        data["sponsor_content_type"] = resolve_content_type(raw_ct)

        status_ = data.get("status") or "draft"
        if status_ in ("scheduled", "published") and not (data.get("title") or "").strip():
            raise serializers.ValidationError({"title": "Title required to publish or schedule."})

        return data

    def create(self, validated_data):
        # Remove the create_working_copy flag before creating the piece
        validated_data.pop("create_working_copy", None)
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)


class WritingPieceDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for viewing a single piece"""
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    author_avatar = serializers.SerializerMethodField()
    sponsor_name = serializers.SerializerMethodField()
    reading_time = serializers.IntegerField(read_only=True)

    class Meta:
        model = WritingPiece
        fields = [
            "id",
            "title",
            "slug",
            "body_json",
            "excerpt",
            "writing_kind",
            "author_name",
            "author_avatar",
            "sponsor_name",
            "published_at",
            "reading_time",
            "view_count",
            "allow_comments",
            "canonical_url",
        ]
        read_only_fields = fields

    def get_author_avatar(self, obj):
        try:
            return obj.author.profile.avatar.url
        except (AttributeError, ValueError):
            return None

    def get_sponsor_name(self, obj):
        if obj.sponsor:
            return str(obj.sponsor)
        return None


class WritingPieceMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = WritingPiece
        fields = ["id", "slug", "status", "writing_kind", "is_empty"]
        read_only_fields = ["id", "slug", "status"]


class WritingWorkingCopyLightSerializer(serializers.ModelSerializer):
    """Lightweight serializer for autosave operations (no nested data)"""
    piece = WritingPieceMinimalSerializer(read_only=True)

    class Meta:
        model = WritingWorkingCopy
        fields = ["id", "piece", "body_json", "title", "excerpt",
                "last_saved_at", "auto_save_count", "client_session_id"]
        read_only_fields = ["last_saved_at", "auto_save_count"]







# class WritingWorkingCopyLightSerializer(serializers.ModelSerializer):
#     """Lightweight serializer for autosave operations (no nested data)"""
#     class Meta:
#         model = WritingWorkingCopy
#         fields = ['body_json', 'title', 'excerpt', 'last_saved_at', 'auto_save_count', 'client_session_id']
#         read_only_fields = ['last_saved_at', 'auto_save_count']


class AuthorSerializer(serializers.ModelSerializer):
    """Minimal author info for nested serialization"""
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name"]

    def get_display_name(self, obj):
        return obj.get_full_name() or obj.username


class WritingVersionSerializer(serializers.ModelSerializer):
    """Serializer for WritingVersion"""

    class Meta:
        model = WritingVersion
        fields = [
            "id", "version_no", "title", "excerpt",
            "created_at", "changelog"
        ]
        read_only_fields = fields

# apps/content/serializers.py

class WritingPlacementSerializer(serializers.ModelSerializer):
    # Flatten piece data into placement
    piece_id = serializers.CharField(source="piece.id", read_only=True)
    piece_slug = serializers.CharField(source="piece.slug", read_only=True)
    piece_title = serializers.CharField(source="piece.title", read_only=True)
    piece_body_json = serializers.JSONField(source="piece.body_json", read_only=True)
    piece_status = serializers.CharField(source="piece.status", read_only=True)
    published_at = serializers.DateTimeField(source="piece.published_at", read_only=True)
    pinned_at = serializers.DateTimeField(source="piece.pinned_at", read_only=True)
    author_name = serializers.CharField(source="piece.author_name", read_only=True)
    is_announcement = serializers.SerializerMethodField()
    display = serializers.SerializerMethodField()

    class Meta:
        model = WritingPlacement
        fields = [
            "id",
            "piece_id",
            "piece_slug",
            "piece_title",
            "piece_body_json",
            "piece_status",
            "published_at",
            "visibility",
            "is_pinned",
            "pinned_at",
            "order",
            "created_at",
            "is_announcement",
            "author_name",
            "display",
        ]

    def get_is_announcement(self, obj):
        return obj.piece.writing_kind == "announcement"

    def get_display(self, obj):  # ← ADD THIS METHOD
        d = obj.get_content_for_display()
        return {
            "title": d.get("title"),
            "excerpt": d.get("excerpt", ""),
            "is_excerpt": d.get("is_excerpt", False),
            "body_json": d.get("body_json"),
        }

class WritingPieceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing writing pieces"""
    author = AuthorSerializer(read_only=True)
    placement_count = serializers.SerializerMethodField()
    tags_list = serializers.SerializerMethodField()

    class Meta:
        model = WritingPiece
        fields = [
            "id", "title", "slug", "excerpt", "writing_kind",
            "status", "author", "current_version_no",
            "published_at", "updated_at", "placement_count",
            "reading_time", "tags_list"
        ]
        read_only_fields = fields

    def get_placement_count(self, obj):
        return obj.placements.count()

    def get_tags_list(self, obj):
        try:
            if hasattr(obj, "tags"):
                return [tag.name for tag in obj.tags.all()]
            return []
        except:
            return []

        # # api/writing/serializers.py


class SeedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Seed
        fields = [
            "id", "author", "body_text", "created_at", "updated_at",
            "promoted_to", "context_url", "source",
        ]
        read_only_fields = ["id", "author", "created_at", "updated_at", "promoted_to", "context_url", "source"]

    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)


class SeedUpdateSerializer(serializers.ModelSerializer):
    """
    Tight autosave PATCH: only body_text updates.
    """
    class Meta:
        model = Seed
        fields = ["body_text"]


class WritingCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    author_avatar = serializers.URLField(source="author.profile.avatar.url", read_only=True)
    replies = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    user_has_liked = serializers.SerializerMethodField()

    class Meta:
        model = WritingComment
        fields = ["id", "content", "created_at", "author_name", "author_avatar",
                 "replies", "like_count", "user_has_liked"]
        read_only_fields = ["created_at"]

    def get_replies(self, obj):
        if obj.replies.exists():
            return WritingCommentSerializer(obj.replies.all(), many=True, context=self.context).data
        return []

    def get_like_count(self, obj):
        return obj.likes.count()

    def get_user_has_liked(self, obj):
        user = self.context["request"].user
        return obj.likes.filter(user=user).exists()


class UserMinimalSerializer(serializers.ModelSerializer):
    """Minimal user info for working copy context."""
    class Meta:
        model = User
        fields = ["id", "username"]


class WritingPieceMinimalSerializer(serializers.ModelSerializer):
    """Minimal piece info for working copy context."""
    class Meta:
        model = WritingPiece
        fields = [
            "id", "slug", "title", "writing_kind",
            "status", "created_at", "updated_at", "excerpt"
        ]


class WritingWorkingCopySerializer(serializers.ModelSerializer):
    """
    Serializer for WritingWorkingCopy with nested piece and user info.
    Includes collaboration status and collaborator details.
    """
    piece = WritingPieceMinimalSerializer(read_only=True)
    user = UserMinimalSerializer(read_only=True)

    # Collaboration fields
    is_collaborative = serializers.SerializerMethodField()
    collaborator_count = serializers.SerializerMethodField()
    collaborators = serializers.SerializerMethodField()

    def get_is_collaborative(self, obj):
        """Check if this working copy has collaboration enabled"""
        return obj.dispatch_content is not None

    def get_collaborator_count(self, obj):
        """Return the number of collaborators (excluding the owner)"""
        if not obj.dispatch_content:
            return 0
        # Count all collaborators
        return obj.dispatch_content.collaborators.count()

    def get_collaborators(self, obj):
        """Return minimal collaborator info for avatars/display"""
        if not obj.dispatch_content:
            return []

        from dispatch.api.serializers import DispatchCollaboratorMinimalSerializer
        collaborators = obj.dispatch_content.collaborator_assignments.select_related('user')
        return DispatchCollaboratorMinimalSerializer(collaborators, many=True).data

    class Meta:
        model = WritingWorkingCopy
        fields = [
            "id",
            "piece",
            "user",
            "title",
            "excerpt",
            "body_json",
            "last_saved_at",
            "auto_save_count",
            "client_session_id",
            # Collaboration fields
            "is_collaborative",
            "collaborator_count",
            "collaborators",
        ]
