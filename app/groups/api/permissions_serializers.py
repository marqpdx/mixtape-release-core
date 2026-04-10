# groups/api/permissions_serializers.py
"""
Serializers for group permissions and member decorators
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class PermissionSerializer(serializers.Serializer):
    """Serializer for available permissions"""
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    category = serializers.ChoiceField(choices=['identity', 'capability', 'policy'])


class MemberPermissionsSerializer(serializers.Serializer):
    """Serializer for member permissions in a group"""
    user_id = serializers.UUIDField(source='member_object_id')
    user = serializers.SerializerMethodField()
    roles = serializers.ListField(child=serializers.CharField())
    decorators = serializers.SerializerMethodField()
    permission_profile = serializers.SerializerMethodField()
    is_helper = serializers.SerializerMethodField()

    def get_user(self, membership):
        """Get user info from membership"""
        from accounts.api.serializers import UserSerializer
        user = membership.member_object
        if user:
            return UserSerializer(user).data
        return None

    def get_decorators(self, membership):
        """Get list of decorator codes for this membership"""
        return membership.get_decorator_codes()

    def get_permission_profile(self, membership):
        profile = getattr(membership, "permission_profile", None)
        if not profile:
            return None
        return {
            "id": str(profile.id),
            "code": profile.code,
            "name": profile.name,
            "is_default": profile.is_default,
        }

    def get_is_helper(self, membership):
        user = membership.member_object
        if not user or not hasattr(user, "roles"):
            return False
        return user.roles.filter(name="helper").exists()


class GroupPermissionProfileSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    is_default = serializers.BooleanField()
    sort_order = serializers.IntegerField()
    decorators = serializers.SerializerMethodField()

    def get_decorators(self, profile):
        return list(
            profile.items.select_related("decorator").values_list("decorator__code", flat=True)
        )


class AssignPermissionProfileSerializer(serializers.Serializer):
    profile_id = serializers.CharField(allow_null=True, required=False)


class UpsertGroupPermissionProfileSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    decorators = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )

    def validate_decorators(self, value):
        from groups.services.permission_profiles import get_phase1_membership_decorators

        allowed_codes = set(get_phase1_membership_decorators().keys())
        invalid = [code for code in value if code not in allowed_codes]
        if invalid:
            raise serializers.ValidationError(
                f"Invalid decorators: {', '.join(invalid)}"
            )
        return value


class GrantPermissionSerializer(serializers.Serializer):
    """Serializer for granting a permission"""
    decorator = serializers.CharField(required=True)

    def validate_decorator(self, value):
        """Validate decorator code is in allowed list"""
        from groups.permissions.decorators import MEMBERSHIP_DECORATORS

        if value not in MEMBERSHIP_DECORATORS:
            raise serializers.ValidationError(
                f"Invalid decorator: {value}. Must be one of: {', '.join(MEMBERSHIP_DECORATORS.keys())}"
            )
        return value
