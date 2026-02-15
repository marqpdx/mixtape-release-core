# public_api/serializers.py

from rest_framework import serializers
from profiles.models import UserProfile
from utils.storage.storage_utils import key_to_url


class PublicMemberSerializer(serializers.ModelSerializer):
    """
    Lean public-facing member serializer.
    No email, no roles, no internal fields.
    """
    username = serializers.CharField(source="user.username", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)
    profile_image_url = serializers.SerializerMethodField()
    background_image_url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            "username",
            "display_name",
            "quick_intro",
            "avatar_url",
            "profile_image_url",
            "background_image_url",
            "date_joined",
        ]

    def get_profile_image_url(self, obj):
        return key_to_url(obj.profile_image) if obj.profile_image else None

    def get_background_image_url(self, obj):
        return key_to_url(obj.background_image) if obj.background_image else None
