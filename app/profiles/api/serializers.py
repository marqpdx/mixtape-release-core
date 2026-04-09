# profiles/api/serializers.py

from django.contrib.auth import get_user_model
from rest_framework import serializers

from profiles.models import UserProfile
from utils.storage.storage_utils import key_to_url


User = get_user_model()


class MemberSerializer(serializers.ModelSerializer):
    """
    Public-facing "Member" serializer that combines User + Profile data.
    This is what the frontend will consume via /api/members/ endpoints.
    """
    # Fields from User (via relation)
    id = serializers.UUIDField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)

    # Roles from User
    roles = serializers.SerializerMethodField()

    # Fields from Profile (direct)
    # slug, display_name, quick_intro, avatar_url are from Meta.fields
    profile_image_url = serializers.SerializerMethodField()
    background_image_url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            # From User
            "id", "username", "email", "first_name", "last_name",
            "is_active", "date_joined", "roles",
            # From Profile
            "slug", "display_name", "quick_intro", "right_now",
            "practice_area", "location", "avatar_url",
            "profile_image", "background_image", "bio_json", "bio_markdown",
            "profile_image_url", "background_image_url",
            "created_at", "updated_at",
        ]
        read_only_fields = ["slug", "created_at", "updated_at"]

    def get_roles(self, obj):
        """Extract roles from user"""
        if hasattr(obj.user, "roles"):
            return list(obj.user.roles.values_list("name", flat=True))
        return []

    def get_profile_image_url(self, obj):
        return key_to_url(obj.profile_image) if obj.profile_image else None

    def get_background_image_url(self, obj):
        return key_to_url(obj.background_image) if obj.background_image else None


class MemberUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating member profile (Phase 2).
    Only allows updating profile fields, not user core fields.
    """
    class Meta:
        model = UserProfile
        fields = [
            "display_name",
            "quick_intro",
            "right_now",
            "practice_area",
            "location",
            "avatar_url",
            "profile_image",
            "background_image",
            "bio_json",
            "bio_markdown",
        ]
