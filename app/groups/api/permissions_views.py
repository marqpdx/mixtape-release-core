# groups/api/permissions_views.py
"""
API views for group permissions management
"""

from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from groups.models import Group, GroupMembership
from groups.permissions.decorators import get_available_decorators
from groups.api.permissions_serializers import (
    PermissionSerializer,
    MemberPermissionsSerializer,
    GrantPermissionSerializer,
)

User = get_user_model()


class AvailablePermissionsView(generics.GenericAPIView):
    """
    GET /api/groups/{slug}/permissions/available
    Get list of all available permissions that can be granted
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        # Verify user is an admin
        user_membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not user_membership or not user_membership.is_admin():
            return Response(
                {"error": "Only admins can view available permissions"},
                status=403
            )

        decorators = get_available_decorators()
        serializer = PermissionSerializer(decorators, many=True)
        return Response(serializer.data)


class MemberPermissionsListView(generics.GenericAPIView):
    """
    GET /api/groups/{slug}/members/permissions
    Get permissions for all members in the group
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        # Verify user is an admin
        user_membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not user_membership or not user_membership.is_admin():
            return Response(
                {"error": "Only admins can view member permissions"},
                status=403
            )

        # Get all active memberships for this group (User members only)
        user_ct = ContentType.objects.get_for_model(User)
        memberships = GroupMembership.objects.filter(
            group=group,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            member_content_type=user_ct
        ).select_related('member_content_type').order_by('created_at')

        serializer = MemberPermissionsSerializer(memberships, many=True)
        return Response(serializer.data)


class MemberPermissionManageView(generics.GenericAPIView):
    """
    POST /api/groups/{slug}/members/{user_id}/permissions
    Grant a permission to a member

    DELETE /api/groups/{slug}/members/{user_id}/permissions/{decorator}
    Revoke a permission from a member
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, user_id):
        """Grant permission to member"""
        group = get_object_or_404(Group, slug=slug)

        # Verify requester is an admin
        requester_membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can grant permissions"},
                status=403
            )

        # Validate request data
        serializer = GrantPermissionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        decorator_code = serializer.validated_data['decorator']

        # Get the target member's membership
        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=user_id,
            member_content_type=user_ct,
            is_active=True
        ).first()

        if not membership:
            return Response(
                {"error": "User is not a member of this group"},
                status=404
            )

        # Don't allow modifying admin permissions
        if membership.is_admin():
            return Response(
                {"error": "Cannot modify admin permissions"},
                status=403
            )

        # Add the decorator
        from groups.models.decorators import MembershipDecorator, MembershipHasDecorator
        from groups.permissions import MEMBERSHIP_DECORATORS

        # Get decorator metadata from catalog
        decorator_meta = MEMBERSHIP_DECORATORS.get(decorator_code, {})

        # Get or create the decorator
        decorator, _ = MembershipDecorator.objects.get_or_create(
            code=decorator_code,
            defaults={
                'label': decorator_meta.get('name', decorator_code),
                'description': decorator_meta.get('description', ''),
                'category': decorator_meta.get('category', 'permission'),
            }
        )

        # Add decorator to membership
        MembershipHasDecorator.objects.get_or_create(
            membership=membership,
            decorator=decorator,
            defaults={
                'enabled': True,
                'source': 'manual',
                'assigned_by': request.user,
            }
        )

        # Auto-add 'steward' role if this is the first decorator
        decorator_count = MembershipHasDecorator.objects.filter(
            membership=membership,
            enabled=True
        ).count()

        if decorator_count == 1 and not membership.is_steward():
            membership.grant_role('steward')
            print(f"✅ Auto-promoted {membership.member_object} to steward")

        # Return updated membership
        response_serializer = MemberPermissionsSerializer(membership)
        return Response(response_serializer.data)

    def delete(self, request, slug, user_id, decorator):
        """Revoke permission from member"""
        group = get_object_or_404(Group, slug=slug)

        # Verify requester is an admin
        requester_membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can revoke permissions"},
                status=403
            )

        # Get the target member's membership
        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=user_id,
            member_content_type=user_ct,
            is_active=True
        ).first()

        if not membership:
            return Response(
                {"error": "User is not a member of this group"},
                status=404
            )

        # Don't allow modifying admin permissions
        if membership.is_admin():
            return Response(
                {"error": "Cannot modify admin permissions"},
                status=403
            )

        # Remove the decorator
        from groups.models.decorators import MembershipHasDecorator

        deleted_count = MembershipHasDecorator.objects.filter(
            membership=membership,
            decorator__code=decorator
        ).delete()[0]

        # Auto-remove 'steward' role if no decorators left
        decorator_count = MembershipHasDecorator.objects.filter(
            membership=membership,
            enabled=True
        ).count()

        if decorator_count == 0 and membership.is_steward():
            membership.revoke_role('steward')
            print(f"✅ Auto-demoted {membership.member_object} from steward")

        # Return updated membership
        response_serializer = MemberPermissionsSerializer(membership)
        return Response(response_serializer.data)


class MyPermissionsView(generics.GenericAPIView):
    """
    GET /api/groups/{slug}/my-permissions
    Get current user's permissions in the group
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        # Get user's membership
        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            member_content_type=user_ct,
            is_active=True
        ).first()

        if not membership:
            return Response(
                {"error": "You are not a member of this group"},
                status=403
            )

        # Return role and decorators
        return Response({
            'role': membership.highest_role(),
            'roles': membership.roles,
            'decorators': membership.get_decorator_codes(),
            'is_admin': membership.is_admin(),
            'is_steward': membership.is_steward(),
        })
