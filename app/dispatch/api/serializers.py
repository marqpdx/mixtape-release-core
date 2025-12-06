# dispatch/api/serializers.py

from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import serializers
from django.template.defaultfilters import slugify
from accounts.api.serializers import UserSerializer
from dispatch.models import DispatchDocument, DispatchDocumentVersion, DispatchEditSession, Post
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


class DispatchDocumentSerializer(serializers.ModelSerializer):
    collaborators = UserSerializer(many=True, read_only=True)
    submitted_by = UserSerializer(read_only=True)
    author = UserSerializer(read_only=True)
    sponsor_display = serializers.CharField(read_only=True)
    sponsor_type = serializers.CharField(read_only=True)

    class Meta:
        model = DispatchDocument
        fields = [
            "id",
            "created_at",
            "updated_at",
            "title",
            "slug",
            "description",
            "content",
            "body",  # From BaseContent
            "summary",  # From BaseData
            "is_published",  # Property derived from published_at
            "published_at",
            "is_archived",
            "submitted_by",
            "author",
            "author_name",
            "sponsor_content_type",
            "sponsor_object_id",
            "sponsor_display",
            "sponsor_type",
            "collaborators",
            "yjs_state_updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "created_at",
            "updated_at",
            "submitted_by",
            "author",
            "sponsor_content_type",
            "sponsor_object_id",
            "sponsor_display",
            "sponsor_type",
            "is_published",
            "yjs_state_updated_at",
        ]


class DispatchDocumentVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchDocumentVersion
        fields = '__all__'


class DispatchEditSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DispatchEditSession
        fields = '__all__'
