# dispatch/api/serializers.py

from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import serializers
from django.template.defaultfilters import slugify
from accounts.api.serializers import UserSerializer
from dispatch.models import DispatchContent, DispatchContentVersion, DispatchEditSession, DispatchCollaborator, Post
# from utils.handle_collected_items import handleTagCreate


# class PostSerializer(serializers.ModelSerializer):
#     # Revisit this.
#     # detail_url = serializers.SerializerMethodField()
#     # frontend_url = serializers.SerializerMethodField()

#     class Meta:
#         model = Post
#         fields = [
#             "id",
#             "title",
#             "slug",
#             "summary",
#             "body",
#             "status",
#             "published_at",
#             "submitted_by",
#             "sponsor_content_type",
#             "sponsor_object_id",
#             "author",
#             "author_name",
#             "image",
#             "created_at",
#             "updated_at",
#             # "detail_url",
#             # "frontend_url",
#         ]
#         read_only_fields = [
#             "id",
#             "slug",
#             "created_at",
#             "updated_at",
#             "submitted_by",
#             "sponsor_content_type",
#             "sponsor_object_id",
#         ]

#     def create(self, validated_data):
#         sponsor = validated_data.pop("sponsor", None)
#         submitted_by = validated_data.pop("submitted_by", None)

#         post = Post(**validated_data)

#         if sponsor:
#             post.set_sponsor(sponsor)
#         if submitted_by:
#             post.set_submitted_by(submitted_by)

#         post.save()
#         return post

#     # def get_detail_url(self, obj):
#     #     sponsor = getattr(obj, "sponsor", None)
#     #     if sponsor and hasattr(sponsor, "slug") and isinstance(sponsor, Group):
#     #         return reverse(
#     #             "group-post-detail",
#     #             kwargs={
#     #                 "slug": sponsor.slug,
#     #                 "post_slug": obj.slug,
#     #             }
#     #         )
#     #     return None

#     # def get_frontend_url(self, obj):
#     #     sponsor = getattr(obj, "sponsor", None)
#     #     if isinstance(sponsor, Group) and sponsor.slug:
#     #         return f"/groups/{sponsor.slug}/posts/{obj.slug}"
#     #     return None


class DispatchCollaboratorSerializer(serializers.ModelSerializer):
    """Serializer for collaborator assignments with role information"""
    user = UserSerializer(read_only=True)
    invited_by = UserSerializer(read_only=True)
    user_id = serializers.IntegerField(write_only=True, required=False)
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = DispatchCollaborator
        fields = [
            "id",
            "user",
            "user_id",
            "invited_by",
            "role",
            "role_display",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "invited_by"]


class DispatchContentSerializer(serializers.ModelSerializer):
    """
    Serializer for DispatchContent (collaborative editing decorator layer).

    Note: DispatchContent is NOT publishable content - it's infrastructure
    for collaborative editing. Content lives in WorkingDocument/WritingPiece/WorkingCourse/etc.
    """
    collaborators = UserSerializer(many=True, read_only=True)
    collaborator_details = DispatchCollaboratorSerializer(
        source='collaborator_assignments',
        many=True,
        read_only=True
    )
    collaborator_count = serializers.IntegerField(
        source='collaborators.count',
        read_only=True
    )

    # Role-based counts
    editor_count = serializers.SerializerMethodField()
    commenter_count = serializers.SerializerMethodField()

    # Rescind capability
    can_be_rescinded = serializers.BooleanField(read_only=True)
    has_collaborative_edits = serializers.SerializerMethodField()

    class Meta:
        model = DispatchContent
        fields = [
            # Identity
            "id",
            "yjs_document_id",

            # Collaboration
            "collaborators",           # Simple list of users
            "collaborator_details",    # Full collaborator info with roles
            "collaborator_count",
            "editor_count",            # Number of editors
            "commenter_count",         # Number of commenters/reviewers

            # Content snapshot (for offline viewing)
            "content_snapshot",
            "snapshot_updated_at",

            # Yjs state
            "yjs_state_updated_at",
            "last_edited_by",
            "last_edited_at",
            # Note: yjs_state (binary) excluded from API

            # Lifecycle
            "is_archived",
            "is_active",

            # Rescind collaboration
            "can_be_rescinded",
            "has_collaborative_edits",
            "created_by",

            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "yjs_document_id",
            "collaborators",
            "collaborator_details",
            "collaborator_count",
            "editor_count",
            "commenter_count",
            "yjs_state_updated_at",
            "snapshot_updated_at",
            "last_edited_by",
            "last_edited_at",
            "is_active",
            "can_be_rescinded",
            "has_collaborative_edits",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def get_editor_count(self, obj):
        """Count of collaborators with editor role"""
        return obj.collaborator_assignments.filter(role='editor').count()

    def get_commenter_count(self, obj):
        """Count of collaborators with commenter role"""
        return obj.collaborator_assignments.filter(role='commenter').count()

    def get_has_collaborative_edits(self, obj):
        """Whether anyone besides creator has edited"""
        return obj.has_collaborative_edits()


class DispatchContentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchContentVersion
        fields = '__all__'


class DispatchEditSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchEditSession
        fields = '__all__'
