from rest_framework.permissions import BasePermission


class IsSuperUser(BasePermission):
    """Canonical superuser permission class. Use this instead of inline is_superuser checks."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )
