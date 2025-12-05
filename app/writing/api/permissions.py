# apps/writing/api/permissions.py
from rest_framework.permissions import BasePermission


class IsAuthorOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.author_id == request.user.id or getattr(request.user, "is_staff", False)

