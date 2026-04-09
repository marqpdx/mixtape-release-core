# groups/api/serializers.py

import uuid

from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from accounts.api.serializers import UserSerializer
from groups.models import Group, GroupMembership
from groups.services.groups import GroupService
from groups.models import GroupOverviewLayout
from identity.models import EmblemAvatar
from utils.storage.storage_utils import key_to_url

# from identity.models import EmblemAvatar  # PHASE 3: Deferred
# from groups.utils import prefetch_members
# from utils.storage.storage_utils import key_to_url
from ..models import (
    AnnouncementDismissal,
    EmailStatus,
    Group,
    GroupAnnouncement,
    GroupInvitation,
    GroupMembership,
    InvitationKind,
    InvitationStatus,
    InviteLink,
)

# Group Overview layout constraints
OVERVIEW_BLOCK_TYPES = {
    "welcome",
    "announcements",
    "upcoming_events",
    "recent_posts",
    "member_highlights",
    "stewards",
    "pinned_resources",
    "pinned_writing",
    "quick_links",
}

OVERVIEW_SINGLETON_BLOCKS = {
    "welcome",
    "announcements",
    "upcoming_events",
    "recent_posts",
    "member_highlights",
    "stewards",
    "pinned_resources",
    "pinned_writing",
}

OVERVIEW_WIDTHS = {"full", "two_thirds", "half", "one_third"}
OVERVIEW_VISIBILITY = {"members", "public"}


class GroupOverviewLayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupOverviewLayout
        fields = ("id", "layout_version", "blocks", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_blocks(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("blocks must be a list.")

        seen_singletons: set[str] = set()
        normalized: list[dict] = []

        for block in value:
            if not isinstance(block, dict):
                raise serializers.ValidationError("Each block must be an object.")

            block_id = block.get("id") or str(uuid.uuid4())
            block_type = block.get("type")
            width = block.get("width", "full")
            visibility = block.get("visibility", "members")
            config = block.get("config", {})

            if block_type not in OVERVIEW_BLOCK_TYPES:
                raise serializers.ValidationError(f"Unknown block type: {block_type}")
            if width not in OVERVIEW_WIDTHS:
                raise serializers.ValidationError(f"Unknown width: {width}")
            if visibility not in OVERVIEW_VISIBILITY:
                raise serializers.ValidationError(f"Unknown visibility: {visibility}")
            if not isinstance(config, dict):
                raise serializers.ValidationError("config must be an object.")

            if block_type in OVERVIEW_SINGLETON_BLOCKS:
                if block_type in seen_singletons:
                    raise serializers.ValidationError(f"Duplicate singleton block: {block_type}")
                seen_singletons.add(block_type)

            if block_type == "welcome":
                images = config.get("images", [])
                ctas = config.get("ctas", [])
                if isinstance(images, list) and len(images) > 3:
                    raise serializers.ValidationError("Welcome block images may not exceed 3.")
                if isinstance(ctas, list) and len(ctas) > 2:
                    raise serializers.ValidationError("Welcome block CTAs may not exceed 2.")

            normalized.append(
                {
                    "id": block_id,
                    "type": block_type,
                    "width": width,
                    "visibility": visibility,
                    "config": config,
                }
            )

        return normalized


# ============================================================================
# Emblem inline serializer (reuses identity subsystem)
# ============================================================================
class EmblemInlineSerializer(serializers.ModelSerializer):
    size_48_url = serializers.SerializerMethodField()
    size_96_url = serializers.SerializerMethodField()
    size_192_url = serializers.SerializerMethodField()
    size_512_url = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = EmblemAvatar
        fields = (
            "id",
            "size_48",
            "size_96",
            "size_192",
            "size_512",
            "seed",
            "initials",
            "fg",
            "bg",
            "size_48_url",
            "size_96_url",
            "size_192_url",
            "size_512_url",
            "url",
        )

    def _url(self, key):
        return key_to_url(key)

    def get_size_48_url(self, obj):
        return self._url(obj.size_48)

    def get_size_96_url(self, obj):
        return self._url(obj.size_96)

    def get_size_192_url(self, obj):
        return self._url(obj.size_192)

    def get_size_512_url(self, obj):
        return self._url(obj.size_512)

    def get_url(self, obj):
        return (
            self._url(obj.size_96)
            or self._url(obj.size_48)
            or self._url(obj.size_192)
            or self._url(obj.size_512)
            or self._url(obj.image_path)
        )





class GroupListSerializer(serializers.ModelSerializer):
    """
    Lightweight group data for list views.
    """
    member_count = serializers.SerializerMethodField()
    user_roles = serializers.SerializerMethodField()
    sponsor_group = serializers.SerializerMethodField()

    profile_image_url = serializers.ReadOnlyField()
    background_image_url = serializers.ReadOnlyField()

    emblem = EmblemInlineSerializer(read_only=True)

    def get_member_count(self, obj):
        return obj.memberships.filter(
            is_active=True, is_banned=False, is_evicted=False, is_pending=False
        ).count()

    def get_user_roles(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        membership = GroupService.get_user_membership(obj, request.user)
        return membership.roles if membership else None

    def get_sponsor_group(self, obj):
        """Return parent group info for circles"""
        from django.contrib.contenttypes.models import ContentType

        # Only circles have parent groups
        if obj.group_type != 'circle':
            return None

        # Check if sponsor is a Group
        group_ct = ContentType.objects.get_for_model(Group)
        if obj.sponsor_content_type == group_ct:
            try:
                parent = Group.objects.get(id=obj.sponsor_object_id)
                return {
                    'id': str(parent.id),
                    'slug': parent.slug,
                    'title': parent.title,
                    'group_type': parent.group_type
                }
            except Group.DoesNotExist:
                return None

        # Check if sponsor is a User (member-sponsored circle)
        user_ct = ContentType.objects.get_for_model(User)
        if obj.sponsor_content_type == user_ct:
            try:
                sponsor_user = User.objects.get(id=obj.sponsor_object_id)
                return {
                    'id': str(sponsor_user.id),
                    'username': sponsor_user.username,
                    'display_name': sponsor_user.get_full_name() or sponsor_user.username,
                    'type': 'member'
                }
            except User.DoesNotExist:
                return None

        return None

    class Meta:
        model = Group
        fields = [
            "id", "title", "slug", "description", "group_type", "visibility",
            "profile_image_path",
            "background_image_path",
            "profile_image_url", "background_image_url",         # resolved URLs (use these in UI)
            "emblem",
            "is_active", "created_at", "member_count", "user_roles", "sponsor_group",
        ]

        read_only_fields = [
            "profile_image_url",
            "background_image_url",
        ]


class GroupDetailSerializer(GroupListSerializer):
    # Computed image URLs (read-only, generated on-demand)
    profile_image_url = serializers.ReadOnlyField()
    background_image_url = serializers.ReadOnlyField()

    # Parent group info for circles
    sponsor_group = serializers.SerializerMethodField()

    # write-only inputs for updates
    emblem_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    emblem_avatar_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    # submitted_by_username = serializers.CharField(
    #     source="submitted_by.username", read_only=True
    # )

    def get_sponsor_group(self, obj):
        """Return parent group info for circles"""
        from django.contrib.contenttypes.models import ContentType

        # Only circles have parent groups
        if obj.group_type != 'circle':
            return None

        # Check if sponsor is a Group
        group_ct = ContentType.objects.get_for_model(Group)
        if obj.sponsor_content_type == group_ct:
            try:
                parent = Group.objects.get(id=obj.sponsor_object_id)
                return {
                    'slug': parent.slug,
                    'title': parent.title,
                    'id': str(parent.id)
                }
            except Group.DoesNotExist:
                return None

        return None

    class Meta(GroupListSerializer.Meta):
        fields = (
            list(GroupListSerializer.Meta.fields)
            + [
                # "submitted_by",
                # "submitted_by_username",
                "updated_at",
                # Image storage paths (writable)
                "profile_image_path",
                "background_image_path",
                # Computed image URLs (read-only, generated on-demand)
                "profile_image_url",
                "background_image_url",
                "emblem",
                # Additional content fields
                "summary",
                "body",
                "author_name",
                # Circle parent info
                "sponsor_group",
                # "status",
                # "display_layout",
                # Admission control
                "admission_policy",
                # write-only inputs (included so DRF accepts them on PATCH)
                "emblem_id",
                "emblem_avatar_id",
            ]
        )
        read_only_fields = (
            "member_count",
            "user_roles",
            # "submitted_by",
            # "submitted_by_username",
            "created_at",
            "updated_at",
            # Computed URLs (never writable)
            "profile_image_url",
            "background_image_url",
            # "emblem",  # already read_only=True, this is just redundant safety
        )


class GroupCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new groups.
    """
    tagline = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Group
        fields = [
            "title", "description", "group_type", "visibility",
            # Only the path fields (URLs are computed properties)
            "profile_image_path",
            "background_image_path",
            "summary", "body", "author_name",
            "tagline",
        ]

    def validate_title(self, value):
        """Ensure title is not empty and reasonable length"""
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters.")
        return value.strip()

    def validate(self, data):
        tagline = data.get("tagline")
        summary = data.get("summary")
        if tagline and not summary:
            data["summary"] = tagline
        return data


class GroupMembershipListSerializer(serializers.ModelSerializer):
    """
    Flattened membership data for group member lists.
    Returns all member info in a flat structure for frontend.
    """
    # Member identity (flattened from polymorphic relationship)
    member_id = serializers.SerializerMethodField()
    member_type = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    is_active_user = serializers.SerializerMethodField()
    profile_image = serializers.SerializerMethodField()
    right_now = serializers.SerializerMethodField()

    # Roles - returns all roles as array for frontend
    roles = serializers.SerializerMethodField()

    # Group context
    group_title = serializers.CharField(source="group.title", read_only=True)
    group_slug = serializers.CharField(source="group.slug", read_only=True)

    # Invitation context
    invited_by_username = serializers.SerializerMethodField()

    def get_member_id(self, obj):
        return str(obj.member_object_id)

    def get_member_type(self, obj):
        """Return 'customuser', 'group', etc."""
        return obj.member_content_type.model

    def get_username(self, obj):
        member = obj.member_object
        return getattr(member, "username", None)

    def get_email(self, obj):
        member = obj.member_object
        return getattr(member, "email", None)

    def get_first_name(self, obj):
        member = obj.member_object
        return getattr(member, "first_name", "")

    def get_last_name(self, obj):
        member = obj.member_object
        return getattr(member, "last_name", "")

    def get_display_name(self, obj):
        """Compute display name with fallback logic"""
        member = obj.member_object

        # Try various display name sources
        if hasattr(member, "get_full_name"):
            full_name = member.get_full_name()
            if full_name:
                return full_name

        if hasattr(member, "display_name") and member.display_name:
            return member.display_name

        if hasattr(member, "username"):
            return member.username

        return str(obj.member_object_id)

    def get_is_active_user(self, obj):
        member = obj.member_object
        return getattr(member, "is_active", False)

    def get_profile_image(self, obj):
        member = obj.member_object
        # Profile image is on the Profile model, not the User model
        profile = getattr(member, "profile", None)
        if profile:
            image_key = getattr(profile, "profile_image", None)
            if image_key:
                return key_to_url(image_key)
        return None

    def get_right_now(self, obj):
        member = obj.member_object
        profile = getattr(member, "profile", None)
        return getattr(profile, "right_now", "") if profile else ""

    def get_roles(self, obj):
        """
        Return all roles as array for frontend.
        Maps backend roles to frontend expectations:
        - admin → 'admin'
        - steward → 'moderator'
        - member → 'member'
        """
        backend_roles = obj.roles or []

        # Map each backend role to frontend expectation
        role_mapping = {
            "admin": "admin",
            "steward": "moderator",
            "member": "member",
        }

        return [role_mapping.get(role, role) for role in backend_roles]

    def get_invited_by_username(self, obj):
        if obj.invited_by:
            return obj.invited_by.username
        return None

    class Meta:
        model = GroupMembership
        fields = [
            # Member identity
            "member_id", "member_type", "username", "email",
            "first_name", "last_name", "display_name",
            "is_active_user", "profile_image", "right_now",

            # Membership data
            "roles", "date_joined", "is_active", "is_pending",
            "invited_by_username",

            # Group context
            "group_title", "group_slug",
        ]


class GroupMembershipSearchSerializer(serializers.ModelSerializer):
    """
    Lightweight format for member search/autocomplete within groups
    """
    member_id = serializers.SerializerMethodField()
    member_type = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    def get_member_id(self, obj):
        return str(obj.member_object_id)

    def get_member_type(self, obj):
        return obj.member_content_type.model

    def get_username(self, obj):
        member = obj.member_object
        if hasattr(member, "username"):
            return member.username
        if hasattr(member, "slug"):  # Group member
            return member.slug
        return None

    def get_display_name(self, obj):
        member = obj.member_object
        if hasattr(member, "profile") and member.profile:
            return member.profile.display_name
        if hasattr(member, "title"):  # Group member
            return member.title
        return getattr(member, "username", str(member))

    def get_email(self, obj):
        member = obj.member_object
        return getattr(member, "email", None)

    def get_roles(self, obj):
        """Return all roles as array, mapped to frontend expectations"""
        backend_roles = obj.roles or []
        role_mapping = {
            "admin": "admin",
            "steward": "moderator",
            "member": "member",
        }
        return [role_mapping.get(role, role) for role in backend_roles]

    class Meta:
        model = GroupMembership
        fields = ["member_id", "member_type", "username", "display_name", "email", "roles"]


# ============================================================================
# PHASE 2: Removed duplicate GroupCreateSerializer definition
# ============================================================================
# The correct GroupCreateSerializer is defined earlier in this file (lines 131-149)
# This duplicate version has been removed to prevent conflicts.
# Previous duplicate code:
# class GroupCreateSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = Group
#         fields = ["title", "description", "group_type", "visibility"]
#     def create(self, validated_data):
#         user = self.context.get("request").user
#         validated_data["author"] = user
#         group = Group(**validated_data)
#         group.set_sponsor(user)
#         group.set_submitted_by(user)
#         group.save()
#         return group


# class GroupListSerializer(serializers.ModelSerializer):
#     visibility_display = serializers.CharField(source="get_visibility_display", read_only=True)
#     group_type_display = serializers.CharField(source="get_group_type_display", read_only=True)
#     class Meta:
#         model = Group
#         fields = [
#             "id",
#             "title",
#             "description",
#             "group_type",
#             "group_type_display",
#             "visibility",
#             "visibility_display",
#             "created_at",
#             "profile_image",
#             "slug",
#         ]


# class GroupDetailSerializer(serializers.ModelSerializer):
#     visibility_display = serializers.CharField(source="get_visibility_display", read_only=True)
#     group_type_display = serializers.CharField(source="get_group_type_display", read_only=True)
#     members = serializers.SerializerMethodField()

#     class Meta:
#         model = Group
#         fields = "__all__"
#         read_only_fields = ["id", "submitted_by", "slug", "created_at"]


#     def get_members(self, obj):
#         memberships_qs = obj.memberships.select_related("member_content_type").all()
#         memberships = prefetch_members(memberships_qs)
#         return GroupMembershipSerializer(memberships, many=True, context=self.context).data


class GroupInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupInvitation
        fields = ["id", "invited_email", "message", "token", "invited_user"]
        read_only_fields = ["id", "token", "invited_user"]

    def create(self, validated_data):
        group = self.context["group"]
        invited_by = self.context["request"].user
        invited_user = self.context["invited_user"]
        token = self.context["token"]

        return GroupInvitation.objects.create(
            group=group,
            invited_by=invited_by,
            invited_user=invited_user,
            token=token,
            status="invited",
            **validated_data
        )


class InviteLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = InviteLink
        fields = ["shortcode", "user", "group", "token"]




class GroupInvitationSerializer(serializers.ModelSerializer):
    invited_by = UserSerializer(read_only=True)
    invited_email = serializers.EmailField(required=False)  # Make optional
    invited_username = serializers.CharField(required=False, write_only=True)  # Add this field
    invited_group = serializers.SerializerMethodField()
    group_detail = serializers.SerializerMethodField()
    invitation_kind = serializers.ChoiceField(
        choices=InvitationKind.choices,
        required=False,
        default=InvitationKind.INVITE,
    )

    email_status = serializers.ChoiceField(
        choices=EmailStatus.choices,
        required=False,
        default=EmailStatus.SENDING,
    )

    invitation_status = serializers.ChoiceField(
        choices=InvitationStatus.choices,
        required=False,
        default=InvitationStatus.PENDING,
    )

    def validate(self, data):
        # Ensure either email/username or invited group is provided
        invited_email = data.get("invited_email")
        invited_username = data.get("invited_username")
        invited_group = data.get("invited_group")

        if not invited_email and not invited_username and not invited_group:
            raise serializers.ValidationError(
                "Either invited_email, invited_username, or invited_group must be provided."
            )

        # Only validate email uniqueness if we have an email
        if invited_email:
            group = self.context["group"]
            existing = GroupInvitation.objects.filter(
                group=group,
                invited_email=invited_email,
                invitation_status=InvitationStatus.PENDING,
            )
            if existing.exists():
                raise serializers.ValidationError(
                    f"An active invitation already exists for {invited_email} in this group."
                )

        return data

    class Meta:
        model = GroupInvitation
        fields = [
            "id",
            "invited_email",
            "invited_username",  # Add this
            "invited_group",
            "group_detail",
            "message",
            "invitation_status",
            "invitation_kind",
            "email_status",
            "invited_by",
            "invited_user",
            "group",
            "created_at",
            "updated_at",
            "expires_at",
        ]
        read_only_fields = [
            "id",
            "invited_by",
            "group",
            "created_at",
            "updated_at",
            "expires_at",
        ]

    def create(self, validated_data):
        # Remove invited_username from validated_data since it's not a model field
        validated_data.pop("invited_username", None)

        group = self.context["group"]
        invited_by = self.context["request"].user
        invited_user = self.context["invited_user"]

        return GroupInvitation.objects.create(
            group=group,
            invited_by=invited_by,
            invited_user=invited_user,
            **validated_data,
        )

    def get_invited_group(self, obj):
        if not obj.invited_group:
            return None
        return GroupMinimalSerializer(obj.invited_group).data

    def get_group_detail(self, obj):
        if not obj.group:
            return None
        return GroupMinimalSerializer(obj.group).data





class GroupMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = [
            "id",
            "slug",
            "title",
            "group_type",
            "created_at",
            "profile_image",
        ]


class GroupMembershipSerializer(serializers.ModelSerializer):
    member_type = serializers.SerializerMethodField()
    member_data = serializers.SerializerMethodField()

    class Meta:
        model = GroupMembership
        fields = [
            "id",
            "group",
            "roles",
            "is_active",
            "is_pending",
            "date_joined",
            "member_type",
            "member_data",
        ]

    def get_member_type(self, obj):
        return obj.member_content_type.model

    def get_member_data(self, obj):
        if obj.member_content_type.model == "customuser":
            return UserSerializer(obj.member_object).data
        if obj.member_content_type.model == "group":
            return GroupMinimalSerializer(obj.member_object).data
        return None



# NOTICEBOARD related


class GroupAnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.username", read_only=True)
    author_avatar = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)
    source_type = serializers.SerializerMethodField()

    class Meta:
        model = GroupAnnouncement
        fields = [
            "id", "title", "content", "priority", "position",
            "is_active", "created_at", "updated_at", "expires_at",
            "author_name", "author_avatar", "is_expired",
            "cta_text", "cta_url", "source_type",
            "also_send_notification", "notification_sent_at"
        ]
        read_only_fields = ["created_at", "updated_at", "notification_sent_at"]

    def get_author_avatar(self, obj):
        if obj.author and hasattr(obj.author, "avatar"):
            return obj.author.avatar.url if obj.author.avatar else None
        return None

    def get_source_type(self, obj):
        if obj.source_content_type:
            return obj.source_content_type.model
        return None


class CreateAnnouncementFromContentSerializer(serializers.Serializer):
    """
    Used when creating an announcement from existing content
    (course, event, post, etc.)
    """
    content_type = serializers.CharField(help_text="Model name: 'course', 'event', 'post', etc.")
    content_id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    content = serializers.CharField()
    priority = serializers.ChoiceField(
        choices=["critical", "high", "normal"],
        default="normal"
    )
    cta_text = serializers.CharField(max_length=100, required=False, allow_blank=True)
    cta_url = serializers.CharField(max_length=500, required=False, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    also_send_notification = serializers.BooleanField(default=False)

    def validate_content_type(self, value):
        """Ensure the content type exists"""
        try:
            ContentType.objects.get(model=value.lower())
        except ContentType.DoesNotExist:
            raise serializers.ValidationError(f"Content type '{value}' does not exist")
        return value.lower()


class AnnouncementDismissalSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnnouncementDismissal
        fields = ["id", "dismissal_type", "dismissed_at", "snoozed_until"]
        read_only_fields = ["id", "dismissed_at", "snoozed_until"]
