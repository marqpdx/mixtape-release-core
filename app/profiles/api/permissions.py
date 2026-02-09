# profiles/api/permissions.py

from rest_framework.permissions import BasePermission


class IsProfileOwnerOrStaff(BasePermission):
    """
    Allow access only to the profile owner or staff/superuser.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return getattr(obj, "user_id", None) == user.id
