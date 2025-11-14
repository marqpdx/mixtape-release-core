# groups/api/serializers.py

from rest_framework import serializers
from django.contrib.contenttypes.models import ContentType
from groups.models import Group, GroupMembership
from groups.services.groups import GroupService
# from identity.models import EmblemAvatar  # PHASE 3: Deferred
from users.models import CustomUser

from accounts.api.serializers import UserSerializer
from groups.utils import prefetch_members
from utils.storage.storage_utils import key_to_url
from ..models import AnnouncementDismissal, EmailStatus, Group, GroupAnnouncement, GroupInvitation, GroupMembership, InvitationStatus, InviteLink

# ============================================================================
# PHASE 3: Identity Integration (Deferred)
# ============================================================================
# class EmblemInlineSerializer(serializers.ModelSerializer):
#     size_48_url  = serializers.SerializerMethodField()
#     size_96_url  = serializers.SerializerMethodField()
#     size_192_url = serializers.SerializerMethodField()
#     size_512_url = serializers.SerializerMethodField()
#     # nice convenience: pick the "best" size for badges/headers
#     url          = serializers.SerializerMethodField()
#
#     class Meta:
#         model = EmblemAvatar
#         fields = (
#             "id",
#             # raw keys (keep if you want)
#             "size_48", "size_96", "size_192", "size_512",
#             "seed", "initials", "fg", "bg",
#             # resolved URLs
#             "size_48_url", "size_96_url", "size_192_url", "size_512_url",
#             "url",
#         )
#
#     def _url(self, key):  # tiny helper
#         return key_to_url(key)
#
#     def get_size_48_url(self, obj):  return self._url(obj.size_48)
#     def get_size_96_url(self, obj):  return self._url(obj.size_96)
#     def get_size_192_url(self, obj): return self._url(obj.size_192)
#     def get_size_512_url(self, obj): return self._url(obj.size_512)
#
#     def get_url(self, obj):
#         # choose a default display size
#         return self._url(obj.size_96) or self._url(obj.size_48) \
#             or self._url(obj.size_192) or self._url(obj.size_512)





class GroupListSerializer(serializers.ModelSerializer):
    """
    Lightweight group data for list views.
    """
    member_count = serializers.SerializerMethodField()
    user_roles = serializers.SerializerMethodField()
    # emblem = EmblemInlineSerializer(read_only=True)  # PHASE 3: Deferred

    profile_image_url = serializers.SerializerMethodField()
    background_image_url = serializers.SerializerMethodField()

    def get_member_count(self, obj):
        return obj.memberships.filter(
            is_active=True, is_banned=False, is_evicted=False, is_pending=False
        ).count()

    def get_user_roles(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        membership = GroupService.get_user_membership(obj, request.user)
        return membership.roles if membership else None

    def get_profile_image_url(self, obj):
        key = getattr(obj, "profile_image_path", None) or getattr(obj, "profile_image", None)
        return key_to_url(key)

    def get_background_image_url(self, obj):
        key = getattr(obj, "background_image_path", None) or getattr(obj, "background_image", None)
        return key_to_url(key)

    class Meta:
        model = Group
        fields = [
            'id', 'title', 'slug', 'description', 'group_type', 'visibility',
            'profile_image', 'background_image',                 # raw keys (optional to keep)
            'profile_image_url', 'background_image_url',         # resolved URLs (use these in UI)
            'is_active', 'created_at', 'member_count', 'user_roles', 'emblem',
        ]



class GroupDetailSerializer(GroupListSerializer):
    # write-only inputs for updates
    emblem_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    emblem_avatar_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)

    submitted_by_username = serializers.CharField(
        source="submitted_by.username", read_only=True
    )

    class Meta(GroupListSerializer.Meta):
        fields = (
            list(GroupListSerializer.Meta.fields)
            + [
                "submitted_by",
                "submitted_by_username",
                "updated_at",
                # write-only inputs (included so DRF accepts them on PATCH)
                "emblem_id",
                "emblem_avatar_id",
            ]
        )
        read_only_fields = (
            "member_count",
            "user_roles",
            "submitted_by",
            "submitted_by_username",
            "created_at",
            "updated_at",
            "emblem",  # already read_only=True, this is just redundant safety
        )




class GroupCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating new groups.
    """
    class Meta:
        model = Group
        fields = [
            'title', 'description', 'group_type', 'visibility',
            'profile_image', 'background_image',
        ]

    def validate_title(self, value):
        """Ensure title is not empty and reasonable length"""
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty.")
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters.")
        return value.strip()




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

    # Role - now returns the highest role for frontend
    role = serializers.SerializerMethodField()

    # Group context
    group_title = serializers.CharField(source='group.title', read_only=True)
    group_slug = serializers.CharField(source='group.slug', read_only=True)

    # Invitation context
    invited_by_username = serializers.SerializerMethodField()

    def get_member_id(self, obj):
        return str(obj.member_object_id)

    def get_member_type(self, obj):
        """Return 'customuser', 'group', etc."""
        return obj.member_content_type.model

    def get_username(self, obj):
        member = obj.member_object
        return getattr(member, 'username', None)

    def get_email(self, obj):
        member = obj.member_object
        return getattr(member, 'email', None)

    def get_first_name(self, obj):
        member = obj.member_object
        return getattr(member, 'first_name', '')

    def get_last_name(self, obj):
        member = obj.member_object
        return getattr(member, 'last_name', '')

    def get_display_name(self, obj):
        """Compute display name with fallback logic"""
        member = obj.member_object

        # Try various display name sources
        if hasattr(member, 'get_full_name'):
            full_name = member.get_full_name()
            if full_name:
                return full_name

        if hasattr(member, 'display_name') and member.display_name:
            return member.display_name

        if hasattr(member, 'username'):
            return member.username

        return str(obj.member_object_id)

    def get_is_active_user(self, obj):
        member = obj.member_object
        return getattr(member, 'is_active', False)

    def get_profile_image(self, obj):
        member = obj.member_object
        return getattr(member, 'profile_image', None)

    def get_role(self, obj):
        """
        Return highest role for frontend display.
        Maps backend roles to frontend expectations:
        - admin → 'admin'
        - steward → 'moderator'
        - member → 'member'
        """
        highest = obj.highest_role()

        # Map to frontend expectations
        if highest == 'admin':
            return 'admin'
        elif highest == 'steward':
            return 'moderator'
        else:
            return 'member'

    def get_invited_by_username(self, obj):
        if obj.invited_by:
            return obj.invited_by.username
        return None

    class Meta:
        model = GroupMembership
        fields = [
            # Member identity
            'member_id', 'member_type', 'username', 'email',
            'first_name', 'last_name', 'display_name',
            'is_active_user', 'profile_image',

            # Membership data
            'role', 'date_joined', 'is_active', 'is_pending',
            'invited_by_username',

            # Group context
            'group_title', 'group_slug',
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
    role = serializers.CharField()

    def get_member_id(self, obj):
        return str(obj.member_object_id)

    def get_member_type(self, obj):
        return obj.member_content_type.model

    def get_username(self, obj):
        member = obj.member_object
        if hasattr(member, 'username'):
            return member.username
        elif hasattr(member, 'slug'):  # Group member
            return member.slug
        return None

    def get_display_name(self, obj):
        member = obj.member_object
        if hasattr(member, 'profile') and member.profile:
            return member.profile.display_name
        elif hasattr(member, 'title'):  # Group member
            return member.title
        return getattr(member, 'username', str(member))

    def get_email(self, obj):
        member = obj.member_object
        return getattr(member, 'email', None)

    class Meta:
        model = GroupMembership
        fields = ['member_id', 'member_type', 'username', 'display_name', 'email', 'role']


class GroupCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = [
            "title",
            "description",
            "group_type",
            "visibility",
        ]

    def create(self, validated_data):
        user = self.context.get("request").user
        validated_data["author"] = user

        # Step 1: build instance (does NOT save to DB)
        group = Group(**validated_data)

        # Step 2: set required fields BEFORE saving
        group.set_sponsor(user)
        group.set_submitted_by(user)

        group.save()
        return group


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
            status='invited',
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
        # Ensure either email or username is provided
        invited_email = data.get("invited_email")
        invited_username = data.get("invited_username")

        if not invited_email and not invited_username:
            raise serializers.ValidationError(
                "Either invited_email or invited_username must be provided."
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
            "message",
            "invitation_status",
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
        validated_data.pop('invited_username', None)

        group = self.context["group"]
        invited_by = self.context["request"].user
        invited_user = self.context["invited_user"]

        return GroupInvitation.objects.create(
            group=group,
            invited_by=invited_by,
            invited_user=invited_user,
            **validated_data,
        )





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
            "role",
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
        elif obj.member_content_type.model == "group":
            return GroupMinimalSerializer(obj.member_object).data
        else:
            return None



# NOTICEBOARD related


class GroupAnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.username', read_only=True)
    author_avatar = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)
    source_type = serializers.SerializerMethodField()

    class Meta:
        model = GroupAnnouncement
        fields = [
            'id', 'title', 'content', 'priority', 'position',
            'is_active', 'created_at', 'updated_at', 'expires_at',
            'author_name', 'author_avatar', 'is_expired',
            'cta_text', 'cta_url', 'source_type',
            'also_send_notification', 'notification_sent_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'notification_sent_at']

    def get_author_avatar(self, obj):
        if obj.author and hasattr(obj.author, 'avatar'):
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
        choices=['critical', 'high', 'normal'],
        default='normal'
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
        fields = ['id', 'dismissal_type', 'dismissed_at', 'snoozed_until']
        read_only_fields = ['id', 'dismissed_at', 'snoozed_until']


