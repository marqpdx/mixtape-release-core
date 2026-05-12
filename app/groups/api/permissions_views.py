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
from users.models import Role

from groups.models import Group, GroupMembership
from groups.permissions.decorators import get_available_decorators
from groups.api.permissions_serializers import (
    AssignPermissionProfileSerializer,
    GroupPermissionProfileSerializer,
    PermissionSerializer,
    MemberPermissionsSerializer,
    GrantPermissionSerializer,
    UpsertGroupPermissionProfileSerializer,
)
from groups.services.permission_profiles import (
    assign_permission_profile_to_membership,
    clone_permission_profile,
    create_permission_profile,
    set_default_permission_profile,
    update_permission_profile,
)

User = get_user_model()


def _get_admin_membership(group, user):
    return GroupMembership.objects.filter(
        group=group,
        member_object_id=user.id,
        is_active=True,
    ).first()


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
        ).select_related('member_content_type', 'permission_profile').order_by('created_at')

        serializer = MemberPermissionsSerializer(memberships, many=True)
        return Response(serializer.data)


class GroupPermissionProfileListView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = _get_admin_membership(group, request.user)

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can view permission profiles"},
                status=403,
            )

        profiles = group.permission_profiles.prefetch_related("items__decorator").all()
        serializer = GroupPermissionProfileSerializer(profiles, many=True)
        return Response(serializer.data)

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = _get_admin_membership(group, request.user)

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can create permission profiles"},
                status=403,
            )

        serializer = UpsertGroupPermissionProfileSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)

        profile = create_permission_profile(
            group,
            name=serializer.validated_data["name"],
            description=serializer.validated_data.get("description", ""),
            decorator_codes=serializer.validated_data.get("decorators", []),
        )

        response_serializer = GroupPermissionProfileSerializer(profile)
        return Response(response_serializer.data, status=201)


class GroupPermissionProfileDetailView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug, profile_id):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = _get_admin_membership(group, request.user)

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can update permission profiles"},
                status=403,
            )

        profile = get_object_or_404(
            group.permission_profiles.prefetch_related("items__decorator"),
            id=profile_id,
        )

        serializer = UpsertGroupPermissionProfileSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)

        profile = update_permission_profile(
            profile,
            name=serializer.validated_data["name"],
            description=serializer.validated_data.get("description", ""),
            decorator_codes=serializer.validated_data.get("decorators", []),
            assigned_by=request.user,
        )

        response_serializer = GroupPermissionProfileSerializer(profile)
        return Response(response_serializer.data)


class GroupPermissionProfileCloneView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, profile_id):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = _get_admin_membership(group, request.user)

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can clone permission profiles"},
                status=403,
            )

        profile = get_object_or_404(
            group.permission_profiles.prefetch_related("items__decorator"),
            id=profile_id,
        )
        cloned = clone_permission_profile(profile)
        response_serializer = GroupPermissionProfileSerializer(cloned)
        return Response(response_serializer.data, status=201)


class GroupPermissionProfileSetDefaultView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, profile_id):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = _get_admin_membership(group, request.user)

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can set the default permission profile"},
                status=403,
            )

        profile = get_object_or_404(group.permission_profiles, id=profile_id)
        profile = set_default_permission_profile(profile)
        response_serializer = GroupPermissionProfileSerializer(profile)
        return Response(response_serializer.data)


class MemberPermissionProfileManageView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug, user_id):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = _get_admin_membership(group, request.user)

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can assign permission profiles"},
                status=403,
            )

        serializer = AssignPermissionProfileSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        profile_id = serializer.validated_data.get("profile_id")

        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=user_id,
            member_content_type=user_ct,
            is_active=True,
        ).first()

        if not membership:
            return Response(
                {"error": "User is not a member of this group"},
                status=404,
            )

        profile = None
        if profile_id:
            profile = group.permission_profiles.filter(id=profile_id).first()
            if not profile:
                return Response(
                    {"error": "Permission profile not found for this group"},
                    status=404,
                )

        assign_permission_profile_to_membership(
            membership,
            profile,
            assigned_by=request.user,
        )

        response_serializer = MemberPermissionsSerializer(membership)
        return Response(response_serializer.data)


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

        # Don't allow modifying owner or admin permissions
        if membership.is_owner():
            return Response(
                {"error": "Cannot modify owner permissions"},
                status=403
            )
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

        # Don't allow modifying owner or admin permissions
        if membership.is_owner():
            return Response(
                {"error": "Cannot modify owner permissions"},
                status=403
            )
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


class MemberRoleManageView(generics.GenericAPIView):
    """
    POST /api/groups/{slug}/members/{user_id}/roles
    Body: { "role": "admin" | "steward" }

    DELETE /api/groups/{slug}/members/{user_id}/roles
    Body: { "role": "admin" | "steward" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_memberships(self, request, slug, user_id):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not requester_membership or not requester_membership.is_admin():
            return Response(
                {"error": "Only admins can assign roles"},
                status=403
            )

        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=user_id,
            member_content_type=user_ct,
            is_active=True
        ).first()

        if not membership:
            return None, None, Response(
                {"error": "User is not a member of this group"},
                status=404
            )

        if membership.is_owner():
            return None, None, Response(
                {"error": "Cannot modify owner roles"},
                status=403
            )

        return group, membership, None

    def post(self, request, slug, user_id):
        _, membership, error_response = self._get_memberships(request, slug, user_id)
        if error_response:
            return error_response

        role = (request.data or {}).get("role")
        if role == "owner":
            return Response(
                {"error": "Owner role can only be assigned via ownership change request"},
                status=403
            )
        if role not in ("admin", "steward"):
            return Response({"error": "Invalid role"}, status=400)

        membership.grant_role(role)

        response_serializer = MemberPermissionsSerializer(membership)
        return Response(response_serializer.data)

    def delete(self, request, slug, user_id):
        _, membership, error_response = self._get_memberships(request, slug, user_id)
        if error_response:
            return error_response

        role = (request.data or {}).get("role")
        if role not in ("admin", "steward"):
            return Response({"error": "Invalid role"}, status=400)

        if str(user_id) == str(request.user.id) and role == "admin":
            return Response(
                {"error": "You cannot remove your own admin role here"},
                status=403
            )

        membership.revoke_role(role)

        response_serializer = MemberPermissionsSerializer(membership)
        return Response(response_serializer.data)


class MemberHelperManageView(generics.GenericAPIView):
    """
    POST /api/groups/{slug}/members/{user_id}/helper
    DELETE /api/groups/{slug}/members/{user_id}/helper

    Temporary stopgap for granting Beacon/Lighthouse helper access from the
    group permissions work area.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_membership(self, request, slug, user_id):
        group = get_object_or_404(Group, slug=slug)

        requester_membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not requester_membership or not requester_membership.is_admin():
            return None, None, Response(
                {"error": "Only admins can manage helper access"},
                status=403
            )

        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_object_id=user_id,
            member_content_type=user_ct,
            is_active=True
        ).first()

        if not membership:
            return None, None, Response(
                {"error": "User is not a member of this group"},
                status=404
            )

        target_user = membership.member_object
        if not target_user:
            return None, None, Response(
                {"error": "Target user not found"},
                status=404
            )

        return membership, target_user, None

    def post(self, request, slug, user_id):
        membership, target_user, error_response = self._get_membership(request, slug, user_id)
        if error_response:
            return error_response

        helper_role, _ = Role.objects.get_or_create(name="helper")
        target_user.roles.add(helper_role)

        response_serializer = MemberPermissionsSerializer(membership)
        return Response(response_serializer.data)

    def delete(self, request, slug, user_id):
        membership, target_user, error_response = self._get_membership(request, slug, user_id)
        if error_response:
            return error_response

        helper_role = Role.objects.filter(name="helper").first()
        if helper_role:
            target_user.roles.remove(helper_role)

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
            'permission_profile': (
                {
                    "id": str(membership.permission_profile.id),
                    "code": membership.permission_profile.code,
                    "name": membership.permission_profile.name,
                    "is_default": membership.permission_profile.is_default,
                }
                if membership.permission_profile
                else None
            ),
            'is_owner': membership.is_owner(),
            'is_admin': membership.is_admin(),
            'is_steward': membership.is_steward(),
        })
