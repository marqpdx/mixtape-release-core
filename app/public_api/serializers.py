# public_api/serializers.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from groups.models.group import Group
from groups.models.membership import GroupMembership
from profiles.models import UserProfile
from utils.storage.storage_utils import key_to_url


User = get_user_model()


class PublicMemberSerializer(serializers.ModelSerializer):
    """
    Lean public-facing member serializer.
    No email, no roles, no internal fields.
    """
    username = serializers.CharField(source="user.username", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)
    profile_image_url = serializers.SerializerMethodField()
    background_image_url = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            "username",
            "display_name",
            "quick_intro",
            "avatar_url",
            "bio_json",
            "profile_image_url",
            "background_image_url",
            "date_joined",
            "groups",
        ]

    def get_profile_image_url(self, obj):
        return key_to_url(obj.profile_image) if obj.profile_image else None

    def get_background_image_url(self, obj):
        return key_to_url(obj.background_image) if obj.background_image else None

    def get_groups(self, obj):
        """Return public group affiliations for this member."""
        user_ct = ContentType.objects.get_for_model(User)
        memberships = GroupMembership.objects.filter(
            member_content_type=user_ct,
            member_object_id=obj.user_id,
            is_active=True,
            is_pending=False,
            group__visibility="public",
        ).select_related("group")

        return [
            {
                "title": m.group.title,
                "slug": m.group.slug,
                "group_type": m.group.group_type,
            }
            for m in memberships
        ]


class PublicGroupSerializer(serializers.ModelSerializer):
    """
    Lean public-facing group serializer for the Crossroads Gallery.
    """
    quick_intro = serializers.CharField(source="summary", read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    profile_image_url = serializers.SerializerMethodField()
    background_image_url = serializers.SerializerMethodField()
    emblem = serializers.SerializerMethodField()
    parent_slug = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            "id",
            "slug",
            "title",
            "quick_intro",
            "group_type",
            "member_count",
            "profile_image_url",
            "background_image_url",
            "emblem",
            "parent_slug",
            "decorators",
        ]

    def get_profile_image_url(self, obj):
        return obj.profile_image_url

    def get_background_image_url(self, obj):
        return obj.background_image_url

    def get_emblem(self, obj):
        if not obj.emblem_id:
            return None
        e = obj.emblem
        return {
            "fg": e.fg,
            "bg": e.bg,
            "palette": e.palette or [],
            "image_url": e.size_96_url,
        }

    def get_parent_slug(self, obj):
        group_ct = ContentType.objects.get_for_model(Group)
        if obj.sponsor_content_type_id == group_ct.id:
            # Sponsor is a Group — return its slug
            try:
                parent = Group.objects.only("slug").get(pk=obj.sponsor_object_id)
                return parent.slug
            except Group.DoesNotExist:
                return None
        return None
