from rest_framework.permissions import BasePermission


class IsSuperuser(BasePermission):
    """Ariadne is superuser-only for now (build spec §2a; CTO, 2026-11-02).
    Enforced here at the Django API layer, not just in the frontend route --
    same requirement P3's scaffold flagged as still owed."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)
