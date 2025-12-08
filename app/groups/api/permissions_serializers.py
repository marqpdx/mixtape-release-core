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
    category = serializers.ChoiceField(choices=['content', 'membership', 'administration'])


class MemberPermissionsSerializer(serializers.Serializer):
    """Serializer for member permissions in a group"""
    user_id = serializers.UUIDField(source='member_object_id')
    user = serializers.SerializerMethodField()
    roles = serializers.ListField(child=serializers.CharField())
    decorators = serializers.SerializerMethodField()

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
