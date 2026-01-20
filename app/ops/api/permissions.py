from rest_framework.permissions import BasePermission


class IsSuperuser(BasePermission):
    message = "Superuser access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)
