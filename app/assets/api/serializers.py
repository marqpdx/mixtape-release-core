# assets/api/serializers

from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models import (
    Asset,
    AudioFields,
    DocumentFields,
    GroupAsset,
    ImageFields,
    ProfileAsset,
    VideoFields,
)


User = get_user_model()


class ImageFieldsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageFields
        fields = "__all__"


class VideoFieldsSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoFields
        fields = "__all__"


class DocumentFieldsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFields
        fields = "__all__"


class AudioFieldsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioFields
        fields = "__all__"


class AssetSerializer(serializers.ModelSerializer):
    # Related fields
    image_fields = ImageFieldsSerializer(read_only=True)
    video_fields = VideoFieldsSerializer(read_only=True)
    document_fields = DocumentFieldsSerializer(read_only=True)
    audio_fields = AudioFieldsSerializer(read_only=True)

    privacy = serializers.CharField()

    # Optional: show the linked object content type as a string
    content_type = serializers.SlugRelatedField(
        slug_field="model",
        read_only=True
    )

    class Meta:
        model = Asset
        fields = [
            "id",
            "type",
            "content_type",
            "object_id",
            "file_path",
            "file_name",
            "file_type",
            "file_size",
            "folder_path",
            "upload_status",
            "privacy",
            "created_at",
            "image_fields",
            "video_fields",
            "document_fields",
            "audio_fields",
        ]

    def to_representation(self, instance):
        """
        Remove any nested asset fields if they are None
        """
        data = super().to_representation(instance)

        for nested_field in [
            "image_fields",
            "video_fields",
            "document_fields",
            "audio_fields",
        ]:
            if data.get(nested_field) is None:
                data.pop(nested_field, None)

        return data


class GroupAssetSerializer(serializers.ModelSerializer):
    asset = AssetSerializer(read_only=True)

    class Meta:
        model = GroupAsset
        fields = [
            "id",
            "group",
            "title",
            "description",
            "asset",
            "uploaded_by",
            "is_featured",
            "sort_order",
            "is_deleted",
        ]
        read_only_fields = ["uploaded_by"]


class ProfileAssetSerializer(serializers.ModelSerializer):
    asset = AssetSerializer(read_only=True)

    class Meta:
        model = ProfileAsset
        fields = [
            "id",
            "asset",
            "title",
            "description",
            "profile",
        ]


# class CollectionAssetSerializer(serializers.ModelSerializer):
#     asset = AssetSerializer(read_only=True)

#     class Meta:
#         model = CollectionAsset
#         fields = [
#             "id",
#             "asset",
#             "title",
#             "description",
#             "collection",
#         ]


class GroupAssetUploadSerializer(serializers.Serializer):
    description = serializers.CharField(required=False, allow_blank=True)
    file = serializers.FileField()
    folder_path = serializers.CharField(required=False, allow_blank=True)
    title = serializers.CharField(required=False, allow_blank=True)
    type = serializers.CharField(default="document", required=False)
    privacy = serializers.ChoiceField(
        choices=[
            ("public", "Public"),
            ("partners", "Partners Only"),
            ("members", "Group Members Only"),
            ("admins", "Admins Only"),
        ],
        default="members",
        required=False,
    )





