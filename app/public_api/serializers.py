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
            try:
                parent = Group.objects.only("slug").get(pk=obj.sponsor_object_id)
                return parent.slug
            except Group.DoesNotExist:
                return None
        return None


class PublicGroupDetailSerializer(PublicGroupSerializer):
    """
    Extended serializer for the group detail/landing page.
    Adds: description, parent_title, child_groups, member_preview.
    """
    description = serializers.CharField(read_only=True)
    parent_title = serializers.SerializerMethodField()
    child_groups = serializers.SerializerMethodField()
    member_preview = serializers.SerializerMethodField()

    class Meta(PublicGroupSerializer.Meta):
        fields = PublicGroupSerializer.Meta.fields + [
            "description",
            "parent_title",
            "child_groups",
            "member_preview",
            "admission_policy",
        ]

    def get_parent_title(self, obj):
        group_ct = ContentType.objects.get_for_model(Group)
        if obj.sponsor_content_type_id == group_ct.id:
            try:
                parent = Group.objects.only("title", "slug").get(
                    pk=obj.sponsor_object_id
                )
                return {"title": parent.title, "slug": parent.slug}
            except Group.DoesNotExist:
                return None
        return None

    def get_child_groups(self, obj):
        group_ct = ContentType.objects.get_for_model(Group)
        children = Group.objects.filter(
            sponsor_content_type=group_ct,
            sponsor_object_id=obj.id,
            visibility="public",
            is_active=True,
        ).only("title", "slug", "group_type")[:12]

        return [
            {
                "title": c.title,
                "slug": c.slug,
                "group_type": c.group_type,
            }
            for c in children
        ]

    def get_member_preview(self, obj):
        """Return avatars of up to 8 active members."""
        user_ct = ContentType.objects.get_for_model(User)
        memberships = (
            GroupMembership.objects.filter(
                group=obj,
                member_content_type=user_ct,
                is_active=True,
                is_banned=False,
                is_evicted=False,
                is_pending=False,
            )
            .order_by("-created_at")[:8]
        )

        previews = []
        user_ids = [m.member_object_id for m in memberships]
        profiles = {
            p.user_id: p
            for p in UserProfile.objects.filter(user_id__in=user_ids)
            .select_related("user")
        }

        for uid in user_ids:
            profile = profiles.get(uid)
            if profile:
                previews.append({
                    "username": profile.user.username,
                    "display_name": profile.display_name,
                    "avatar_url": profile.avatar_url or "",
                })

        return previews
