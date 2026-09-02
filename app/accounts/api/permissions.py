from rest_framework.permissions import BasePermission


class IsSuperUser(BasePermission):
    """Canonical superuser permission class. Use this instead of inline is_superuser checks."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )


class IsEmailVerified(BasePermission):
    """
    Requires the authenticated user to have a verified email address.
    Invite-accepted accounts are verified at activation time. Open-registration
    accounts must click the verification link sent at signup.
    Returns 403 with a structured detail so the frontend can prompt verification.
    """

    message = "Email verification required. Check your inbox for a verification link."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "email_verified", True)
        )
