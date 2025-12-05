# /api/serializers/mixins.py

from rest_framework import serializers


class RoleMixin(serializers.Serializer):
    roles = serializers.SerializerMethodField()

    def get_roles(self, obj):
        if not hasattr(obj, "_cached_roles"):
            obj._cached_roles = obj.roles.all()
        return [role.name for role in obj._cached_roles]
