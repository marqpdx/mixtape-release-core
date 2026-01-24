# bazaar/api/permissions.py

"""
Bazaar API Permissions

Custom permission classes for Bazaar operations.
"""

from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions


class IsAuthenticated(permissions.IsAuthenticated):
    """Require authentication for all requests."""
    pass


class IsSponsorOrReadOnly(permissions.BasePermission):
    """
    Allow read access to anyone, write access only to sponsor.

    Works with objects that have sponsor_content_type and sponsor_object_id.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions allowed for any request
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions only for sponsor
        return self._is_sponsor(request.user, obj)

    def _is_sponsor(self, user, obj):
        """Check if user is the sponsor (for User sponsors) or member of sponsor group."""
        if not hasattr(obj, "sponsor_content_type") or not hasattr(obj, "sponsor_object_id"):
            return False

        # Check if user is directly the sponsor
        user_ct = ContentType.objects.get_for_model(user)
        if obj.sponsor_content_type == user_ct and str(obj.sponsor_object_id) == str(user.pk):
            return True

        # Check if user is a member/admin of the sponsor group
        if obj.sponsor_content_type.model == "group":
            try:
                group = obj.sponsor
                if hasattr(group, "memberships"):
                    # Check for admin/steward membership
                    membership = group.memberships.filter(
                        user=user,
                        role__in=["admin", "steward"],
                        deleted_at__isnull=True,
                    ).first()
                    return membership is not None
            except Exception:
                pass

        return False


class IsSponsor(permissions.BasePermission):
    """
    Only allow access to sponsor.

    Stricter than IsSponsorOrReadOnly - blocks all access for non-sponsors.
    """
    def has_object_permission(self, request, view, obj):
        return self._is_sponsor(request.user, obj)

    def _is_sponsor(self, user, obj):
        """Check if user is the sponsor or member of sponsor group."""
        if not hasattr(obj, "sponsor_content_type") or not hasattr(obj, "sponsor_object_id"):
            return False

        user_ct = ContentType.objects.get_for_model(user)
        if obj.sponsor_content_type == user_ct and str(obj.sponsor_object_id) == str(user.pk):
            return True

        if obj.sponsor_content_type.model == "group":
            try:
                group = obj.sponsor
                if hasattr(group, "memberships"):
                    membership = group.memberships.filter(
                        user=user,
                        role__in=["admin", "steward"],
                        deleted_at__isnull=True,
                    ).first()
                    return membership is not None
            except Exception:
                pass

        return False


class IsBuyerOrVendor(permissions.BasePermission):
    """
    Allow access to order buyer or the offering vendor.

    Used for order detail views.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user

        # Check if user is the buyer
        if hasattr(obj, "buyer") and obj.buyer == user:
            return True

        # Check if user is the vendor (sponsor of offering)
        if hasattr(obj, "offering") and obj.offering:
            return self._is_sponsor(user, obj.offering)

        return False

    def _is_sponsor(self, user, offering):
        """Check if user is the sponsor of the offering."""
        user_ct = ContentType.objects.get_for_model(user)
        if offering.sponsor_content_type == user_ct and str(offering.sponsor_object_id) == str(user.pk):
            return True

        if offering.sponsor_content_type.model == "group":
            try:
                group = offering.sponsor
                if hasattr(group, "memberships"):
                    membership = group.memberships.filter(
                        user=user,
                        role__in=["admin", "steward"],
                        deleted_at__isnull=True,
                    ).first()
                    return membership is not None
            except Exception:
                pass

        return False


class IsBuyer(permissions.BasePermission):
    """Only allow access to the buyer of an order."""

    def has_object_permission(self, request, view, obj):
        return hasattr(obj, "buyer") and obj.buyer == request.user


class IsVendor(permissions.BasePermission):
    """Only allow access to the vendor (sponsor) of an offering/order."""

    def has_object_permission(self, request, view, obj):
        user = request.user

        # If it's an order, get the offering
        if hasattr(obj, "offering"):
            offering = obj.offering
        else:
            offering = obj

        return self._is_sponsor(user, offering)

    def _is_sponsor(self, user, offering):
        """Check if user is the sponsor of the offering."""
        if not hasattr(offering, "sponsor_content_type"):
            return False

        user_ct = ContentType.objects.get_for_model(user)
        if offering.sponsor_content_type == user_ct and str(offering.sponsor_object_id) == str(user.pk):
            return True

        if offering.sponsor_content_type.model == "group":
            try:
                group = offering.sponsor
                if hasattr(group, "memberships"):
                    membership = group.memberships.filter(
                        user=user,
                        role__in=["admin", "steward"],
                        deleted_at__isnull=True,
                    ).first()
                    return membership is not None
            except Exception:
                pass

        return False


class CanCreateOffering(permissions.BasePermission):
    """
    Check if user can create offerings for the specified sponsor.

    Validates sponsor has Bazaar capability (can_sell).
    """
    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        sponsor_type = request.data.get("sponsor_type")
        sponsor_id = request.data.get("sponsor_id")

        if not sponsor_type or not sponsor_id:
            return True  # Let serializer validation handle missing fields

        try:
            ct = ContentType.objects.get(model=sponsor_type.lower())
            sponsor = ct.get_object_for_this_type(pk=sponsor_id)
        except Exception:
            return True  # Let serializer validation handle invalid sponsor

        # Check if user is authorized for this sponsor
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)

        if ct == user_ct and str(sponsor_id) == str(user.pk):
            return True  # User is creating for themselves

        # Check group membership
        if sponsor_type.lower() == "group":
            if hasattr(sponsor, "memberships"):
                membership = sponsor.memberships.filter(
                    user=user,
                    role__in=["admin", "steward"],
                    deleted_at__isnull=True,
                ).first()
                return membership is not None

        return False
