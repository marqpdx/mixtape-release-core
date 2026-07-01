# api/writing/serializers.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import serializers
import hashlib

from utils.shared.contenttypes import resolve_content_type
from writing.choices import ContentStatus

from ..models import (
    LeafComment,
    LeafPlacement,
    LeafPlacementReaction,
    Seed,
    WritingComment,
    WritingPiece,
    # WritingPlacement,  # Replaced by ContentPlacement in app.publishing
    WritingSeries,
    WritingVersion,
    WorkingDocument,
    WritingSynopsis,
    SplitSuggestion,
    WritingAnalysisSession,
    WritingFidelityReport,
    WritingSuggestedRevision,
)
from commons.models import Leaf


User = get_user_model()


def _get_tag_titles_for_piece(piece: WritingPiece) -> list[str]:
    try:
        from classifications.models import Tag, ClassificationUsage
        tag_ct = ContentType.objects.get_for_model(Tag)
        piece_ct = ContentType.objects.get_for_model(WritingPiece)
        tag_ids = ClassificationUsage.objects.filter(
            classification_client_content_type=piece_ct,
            classification_client_object_id=str(piece.id),
            classification_content_type=tag_ct,
        ).values_list("classification_object_id", flat=True)
        tags = Tag.objects.filter(id__in=tag_ids).order_by("title")
        return [tag.title for tag in tags]
    except Exception:
        return []

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
        is_create = self.instance is None
        raw_ct = self.initial_data.get("sponsor_content_type")
        if is_create:
            if not raw_ct:
                raise serializers.ValidationError({"sponsor": "Sponsor is required (content_type + object_id)."})
            data["sponsor_content_type"] = resolve_content_type(raw_ct)
        elif raw_ct:
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


class WritingSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = WritingSeries
        fields = ["id", "title", "slug", "phase_num", "subtitle", "group"]
        read_only_fields = ["id"]


class WritingPieceDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for viewing a single piece"""
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    author_avatar = serializers.SerializerMethodField()
    sponsor_name = serializers.SerializerMethodField()
    reading_time = serializers.IntegerField(read_only=True)
    series = WritingSeriesSerializer(read_only=True)

    class Meta:
        model = WritingPiece
        fields = [
            "id",
            "title",
            "slug",
            "body_json",
            "excerpt",
            "writing_kind",
            "enable_outline",
            "author_name",
            "author_avatar",
            "sponsor_name",
            "published_at",
            "reading_time",
            "view_count",
            "allow_comments",
            "canonical_url",
            "series",
            "series_order",
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
        fields = ["id", "slug", "status", "writing_kind", "is_empty", "target_wordcount", "suggest_splits"]
        read_only_fields = ["id", "slug", "status"]


class WritingPieceCatalogSerializer(serializers.ModelSerializer):
    """Lightweight serializer for catalog/list views. No body_json."""
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    series = WritingSeriesSerializer(read_only=True)

    class Meta:
        model = WritingPiece
        fields = [
            "id",
            "title",
            "slug",
            "excerpt",
            "writing_kind",
            "author_name",
            "published_at",
            "reading_time",
            "series",
            "series_order",
        ]
        read_only_fields = fields


class SplitSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SplitSuggestion
        fields = ["id", "status", "suggestions", "word_count_at_suggestion", "generated_at"]
        read_only_fields = fields


class WritingAnalysisExportRequestSerializer(serializers.Serializer):
    planner_type = serializers.CharField(required=False, allow_blank=True, max_length=32, default="")
    planner_label = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")


class WritingAnalysisSessionSerializer(serializers.ModelSerializer):
    source_piece_id = serializers.UUIDField(source="source_piece_id", read_only=True)

    class Meta:
        model = WritingAnalysisSession
        fields = [
            "id",
            "source_piece_id",
            "source_revision_hash",
            "export_version",
            "planner_type",
            "planner_label",
            "status",
            "completed_at",
            "created_at",
            "updated_at",
            "warnings",
        ]
        read_only_fields = fields


class WritingSuggestedRevisionCreateSerializer(serializers.Serializer):
    title_suffix = serializers.CharField(required=False, allow_blank=True, max_length=64, default="Suggested Revision")


class WritingSuggestedRevisionSerializer(serializers.ModelSerializer):
    source_piece_id = serializers.UUIDField(source="source_piece_id", read_only=True)
    suggested_piece_id = serializers.UUIDField(source="suggested_piece_id", read_only=True)
    analysis_session_id = serializers.UUIDField(source="analysis_session_id", read_only=True)

    class Meta:
        model = WritingSuggestedRevision
        fields = [
            "id",
            "source_piece_id",
            "suggested_piece_id",
            "analysis_session_id",
            "source_revision_hash",
            "derivation_type",
            "created_at",
        ]
        read_only_fields = fields


class WritingFidelityReportSerializer(serializers.ModelSerializer):
    analysis_session_id = serializers.UUIDField(source="analysis_session_id", read_only=True)
    suggested_revision_id = serializers.UUIDField(source="suggested_revision_id", read_only=True)
    source_piece_id = serializers.UUIDField(source="source_piece_id", read_only=True)
    suggested_piece_id = serializers.UUIDField(source="suggested_piece_id", read_only=True)

    class Meta:
        model = WritingFidelityReport
        fields = [
            "id",
            "analysis_session_id",
            "suggested_revision_id",
            "source_piece_id",
            "suggested_piece_id",
            "source_revision_hash",
            "report_version",
            "report_payload",
            "created_at",
        ]
        read_only_fields = fields


class WorkingDocumentLightSerializer(serializers.ModelSerializer):
    """Lightweight serializer for autosave operations (no nested data)"""
    piece = WritingPieceMinimalSerializer(read_only=True)

    class Meta:
        model = WorkingDocument
        fields = ["id", "piece", "body_json", "title", "excerpt",
                "last_saved_at", "auto_save_count", "client_session_id"]
        read_only_fields = ["last_saved_at", "auto_save_count"]









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

# WritingPlacementSerializer - DEPRECATED
# Replaced by ContentPlacement in app.publishing
# Will be reimplemented in Phase 5 using the universal publishing system
#
# class WritingPlacementSerializer(serializers.ModelSerializer):
#     ...

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
            "reading_time", "tags_list", "enable_outline"
        ]
        read_only_fields = fields

    def get_placement_count(self, obj):
        return obj.placements.count()

    def get_tags_list(self, obj):
        return _get_tag_titles_for_piece(obj)

        # # api/writing/serializers.py


class SeedSerializer(serializers.ModelSerializer):
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = Seed
        fields = [
            "id",
            "author",
            "body_text",
            "kind",
            "status",
            "audio_file",
            "audio_url",
            "transcript_text",
            "edited_after_transcription",
            "transcript_created_at",
            "transcript_error",
            "transcript_provider",
            "transcript_model",
            "transcript_backend",
            "created_at",
            "updated_at",
            "promoted_to",
            "context_url",
            "source",
        ]
        read_only_fields = [
            "id",
            "author",
            "created_at",
            "updated_at",
            "promoted_to",
            "context_url",
            "source",
            "audio_file",
            "audio_url",
        ]

    def create(self, validated_data):
        validated_data["author"] = self.context["request"].user
        return super().create(validated_data)

    def get_audio_url(self, obj):
        try:
            return obj.audio_file.url if obj.audio_file else None
        except Exception:
            return None


class SeedUpdateSerializer(serializers.ModelSerializer):
    """
    Tight autosave PATCH: only body_text updates.
    """
    class Meta:
        model = Seed
        fields = ["body_text"]

    def update(self, instance, validated_data):
        body_text = validated_data.get("body_text", instance.body_text or "")
        instance.body_text = body_text
        body_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest() if body_text is not None else ""
        instance.body_hash = body_hash
        if instance.transcript_hash:
            instance.edited_after_transcription = body_hash != instance.transcript_hash
        instance.save(update_fields=["body_text", "body_hash", "edited_after_transcription", "updated_at"])
        return instance


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
    tags_list = serializers.SerializerMethodField()
    series_id = serializers.UUIDField(source="series.id", read_only=True, allow_null=True, default=None)
    series_title = serializers.CharField(source="series.title", read_only=True, allow_null=True, default=None)
    series_phase_num = serializers.IntegerField(source="series.phase_num", read_only=True, allow_null=True, default=None)

    class Meta:
        model = WritingPiece
        fields = [
            "id", "slug", "title", "writing_kind",
            "status", "created_at", "updated_at", "excerpt", "tags_list", "enable_outline",
            "series_id", "series_title", "series_phase_num", "series_order",
        ]

    def get_tags_list(self, obj):
        return _get_tag_titles_for_piece(obj)


class WorkingDocumentSerializer(serializers.ModelSerializer):
    """
    Serializer for WorkingDocument with nested piece and user info.
    Includes collaboration status and collaborator details.
    """
    piece = WritingPieceMinimalSerializer(read_only=True)
    user = UserMinimalSerializer(read_only=True)

    # Collaboration fields
    is_collaborative = serializers.SerializerMethodField()
    collaborator_count = serializers.SerializerMethodField()
    collaborators = serializers.SerializerMethodField()

    # Living Book field
    living_book_id = serializers.SerializerMethodField()

    def get_living_book_id(self, obj):
        lb_id = obj.piece.living_books_as_trunk.values_list('id', flat=True).first()
        return str(lb_id) if lb_id else None

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
        model = WorkingDocument
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
            # Living Book
            "living_book_id",
        ]


class WorkingDocumentListSerializer(WorkingDocumentSerializer):
    """List serializer that excludes body_json, adds a short body_preview instead."""

    body_preview = serializers.SerializerMethodField()

    def get_body_preview(self, obj):
        """Extract first 300 chars of plain text from body_json for list previews.

        Collaborative docs save to DispatchContent.content_snapshot (not wc.body_json),
        so for those we read content_snapshot. Solo docs fall back to piece.body_json
        only when auto_save_count == 0 (never user-edited)."""
        body = obj.body_json

        if obj.dispatch_content:
            # Collaborative: collab autosave writes to content_snapshot, not wc.body_json.
            dc_body = obj.dispatch_content.content_snapshot
            if dc_body and isinstance(dc_body, dict) and dc_body.get("content"):
                wc_nodes = len(body.get("content", [])) if isinstance(body, dict) else 0
                dc_nodes = len(dc_body["content"])
                if wc_nodes < dc_nodes:
                    body = dc_body
        elif obj.auto_save_count == 0:
            # Solo, never autosaved: fall back to piece.body_json if richer.
            piece_body = obj.piece.body_json if obj.piece_id else None
            piece_has_content = piece_body and isinstance(piece_body, dict) and piece_body.get("content")
            if piece_has_content:
                wc_nodes = len(body.get("content", [])) if isinstance(body, dict) else 0
                piece_nodes = len(piece_body["content"])
                if wc_nodes < piece_nodes:
                    body = piece_body
        if not body or not isinstance(body, dict):
            return ""
        content = body.get("content", [])
        if not content:
            return ""

        parts = []
        remaining = 300

        def walk(node):
            nonlocal remaining
            if remaining <= 0:
                return
            if isinstance(node, dict):
                if node.get("type") == "text":
                    text = node.get("text", "")
                    parts.append(text[:remaining])
                    remaining -= len(text)
                for child in node.get("content", []):
                    if remaining <= 0:
                        break
                    walk(child)

        for block in content:
            if remaining <= 0:
                break
            walk(block)

        return "".join(parts)

    class Meta(WorkingDocumentSerializer.Meta):
        fields = [
            f for f in WorkingDocumentSerializer.Meta.fields
            if f != "body_json"
        ] + ["body_preview"]


# ============================================================================
# Leaf & LeafComment Serializers
# ============================================================================

class LeafAuthorSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "avatar_url"]

    def get_display_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_avatar_url(self, obj):
        try:
            return obj.profile.avatar.url
        except (AttributeError, ValueError):
            return None


class LeafCommentSerializer(serializers.ModelSerializer):
    author = LeafAuthorSerializer(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = LeafComment
        fields = [
            "id", "author", "content", "parent", "placement",
            "is_approved", "is_flagged",
            "created_at", "updated_at", "replies",
        ]
        read_only_fields = [
            "id", "author", "placement", "is_approved", "is_flagged",
            "created_at", "updated_at",
        ]

    def get_replies(self, obj):
        if hasattr(obj, "replies") and obj.replies.exists():
            return LeafCommentSerializer(
                obj.replies.filter(is_approved=True), many=True, context=self.context
            ).data
        return []


class LeafSerializer(serializers.ModelSerializer):
    author = LeafAuthorSerializer(read_only=True)
    is_reference = serializers.BooleanField(read_only=True)
    comment_count = serializers.SerializerMethodField()
    source_type = serializers.SerializerMethodField()
    source_title = serializers.SerializerMethodField()
    image_file = serializers.SerializerMethodField()
    audio_file = serializers.SerializerMethodField()

    class Meta:
        model = Leaf
        fields = [
            "id", "author", "body_text", "body_json", "caption",
            "kind", "origin_seed", "promoted_to",
            "audio_file", "image_file", "link_url", "link_preview",
            "source_content_type", "source_object_id", "source_type", "source_title",
            "is_reference", "visibility", "published_at",
            "created_at", "updated_at", "comment_count",
        ]
        read_only_fields = [
            "id", "author", "origin_seed", "promoted_to",
            "source_content_type", "source_object_id",
            "is_reference", "published_at", "created_at", "updated_at",
        ]

    def get_image_file(self, obj):
        if obj.image_file:
            return obj.image_file.url
        return None

    def get_audio_file(self, obj):
        if obj.audio_file:
            return obj.audio_file.url
        return None

    def get_comment_count(self, obj):
        return obj.placements.filter(
            comments__is_approved=True,
            comments__parent__isnull=True,
        ).distinct().count()

    def get_source_type(self, obj):
        if obj.source_content_type:
            return obj.source_content_type.model
        return None

    def get_source_title(self, obj):
        if obj.source_content_type_id and obj.source_object_id:
            try:
                source_obj = obj.source
                return getattr(source_obj, "title", str(source_obj))
            except Exception:
                return None
        return None


class LeafCreateSerializer(serializers.Serializer):
    """For quick_post_leaf — direct creation from Composer."""
    body_text = serializers.CharField(required=False, default="", allow_blank=True)
    body_json = serializers.JSONField(required=False, default=dict)
    kind = serializers.ChoiceField(choices=Leaf.LEAF_KIND_CHOICES, default="text")
    link_url = serializers.URLField(required=False, allow_null=True)
    image_file = serializers.UUIDField(required=False, allow_null=True)
    publish = serializers.BooleanField(required=False, default=True)


class ReferenceLeafCreateSerializer(serializers.Serializer):
    """For create_reference_leaf — curated card pointing to other content."""
    source_content_type = serializers.CharField()
    source_object_id = serializers.UUIDField()
    caption = serializers.CharField(required=False, default="", allow_blank=True)


class LeafPlacementReactionSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)

    class Meta:
        model = LeafPlacementReaction
        fields = ["id", "user_id", "reaction_name", "created_at"]
        read_only_fields = ["id", "user_id", "created_at"]


class LeafPlacementSerializer(serializers.ModelSerializer):
    leaf = LeafSerializer(read_only=True)
    placed_by = LeafAuthorSerializer(read_only=True)
    comment_count = serializers.SerializerMethodField()
    reaction_counts = serializers.SerializerMethodField()
    viewer_reactions = serializers.SerializerMethodField()

    class Meta:
        model = LeafPlacement
        fields = [
            "id", "leaf", "placed_by",
            "target_content_type", "target_object_id",
            "status", "rescinded_at", "visibility",
            "comment_count", "reaction_counts", "viewer_reactions",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "leaf", "placed_by", "rescinded_at",
            "created_at", "updated_at",
        ]

    def get_comment_count(self, obj):
        return obj.comments.filter(is_approved=True, parent__isnull=True).count()

    def get_reaction_counts(self, obj):
        from django.db.models import Count
        qs = obj.reactions.values("reaction_name").annotate(count=Count("id"))
        return {item["reaction_name"]: item["count"] for item in qs}

    def get_viewer_reactions(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return []
        return list(
            obj.reactions.filter(user=request.user).values_list("reaction_name", flat=True)
        )


class LeafPlacementCreateSerializer(serializers.Serializer):
    """Multi-target placement creation."""
    leaf_id = serializers.UUIDField()
    targets = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
    )


class WritingSynopsisSerializer(serializers.ModelSerializer):
    class Meta:
        model = WritingSynopsis
        fields = [
            "id",
            "piece",
            "canonical_url",
            "title",
            "teaser",
            "description",
            "commentary",
            "thumbnail_url",
            "hero_image_url",
            "author_name",
            "sponsor_name",
            "sponsor_type",
            "published_at",
            "visibility",
            "status",
            "source_version",
            "generated_by",
            "linkedin_copy",
            "linkedin_copy_generated_by",
            "linkedin_copy_extended",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "piece", "published_at", "source_version",
            "generated_by", "created_at", "updated_at",
        ]
