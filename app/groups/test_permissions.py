"""
Unit tests for PermissionService (Phase 1: Foundation)

Tests the role-based permission computation logic.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from groups.models import Group, GroupMembership
from groups.services.permissions import (
    PermissionService,
    ROLE_PERMISSIONS,
    can_create_course,
    can_manage_members,
    can_edit_group,
)

User = get_user_model()


class PermissionServiceTestCase(TestCase):
    """Test suite for PermissionService"""

    def setUp(self):
        """Create test fixtures"""
        # Create test users
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='user1@test.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='user2@test.com',
            password='testpass123'
        )
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@test.com',
            password='adminpass123'
        )

        # Create test groups
        self.group1 = Group.objects.create(
            title='Test Group 1',
            slug='test-group-1',
            description='First test group',
            group_type='community',
            decorators=[],
            additional_permissions=[]
        )
        self.group2 = Group.objects.create(
            title='Test Group 2',
            slug='test-group-2',
            description='Second test group',
            group_type='community',
            decorators=[],
            additional_permissions=[]
        )

        # Get user content type for memberships
        self.user_ct = ContentType.objects.get_for_model(User)

    def test_unauthenticated_user_has_no_permissions(self):
        """Test that unauthenticated users have no permissions"""
        result = PermissionService.compute_user_permissions(None)

        self.assertEqual(result['granted'], [])
        self.assertEqual(result['effective'], [])
        self.assertEqual(result['groups'], {})

    def test_user_with_no_memberships_has_no_permissions(self):
        """Test that users with no group memberships have no permissions"""
        result = PermissionService.compute_user_permissions(self.user1)

        self.assertEqual(result['granted'], [])
        self.assertEqual(result['effective'], [])
        self.assertEqual(result['groups'], {})

    def test_admin_role_permissions(self):
        """Test that admin role grants all expected permissions"""
        # Create admin membership
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        # Admin should have all admin permissions
        admin_perms = set(ROLE_PERMISSIONS['admin'])
        self.assertEqual(set(result['granted']), admin_perms)
        self.assertEqual(set(result['effective']), admin_perms)

        # Check group-specific data
        self.assertIn('test-group-1', result['groups'])
        group_data = result['groups']['test-group-1']
        # The save() method automatically adds 'member' if not present
        self.assertEqual(set(group_data['roles']), {'member', 'admin'})
        self.assertEqual(set(group_data['permissions']), admin_perms)

    def test_steward_role_permissions(self):
        """Test that steward role grants expected permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['steward'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        steward_perms = set(ROLE_PERMISSIONS['steward'])
        self.assertEqual(set(result['granted']), steward_perms)

        # Steward should have some admin permissions
        self.assertIn('create_course', result['granted'])
        self.assertIn('invite_members', result['granted'])

        # But not all admin permissions
        self.assertNotIn('manage_members', result['granted'])
        self.assertNotIn('delete_course', result['granted'])

    def test_coordinator_role_permissions(self):
        """Test that coordinator role grants expected permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['coordinator'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        coordinator_perms = set(ROLE_PERMISSIONS['coordinator'])
        self.assertEqual(set(result['granted']), coordinator_perms)

        # Coordinator can create and edit courses
        self.assertIn('create_course', result['granted'])
        self.assertIn('edit_course', result['granted'])

        # But cannot publish or manage members
        self.assertNotIn('publish_course', result['granted'])
        self.assertNotIn('invite_members', result['granted'])

    def test_member_role_permissions(self):
        """Test that member role grants expected permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['member'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        member_perms = set(ROLE_PERMISSIONS['member'])
        self.assertEqual(set(result['granted']), member_perms)

        # Member can view and enroll
        self.assertIn('view_content', result['granted'])
        self.assertIn('enroll_in_courses', result['granted'])

        # But cannot edit or manage
        self.assertNotIn('create_course', result['granted'])
        self.assertNotIn('edit_course', result['granted'])

    def test_multiple_roles_in_one_group(self):
        """Test that multiple roles accumulate permissions correctly"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['coordinator', 'member'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        # Should have union of both role permissions
        expected_perms = set(ROLE_PERMISSIONS['coordinator']) | set(ROLE_PERMISSIONS['member'])
        self.assertEqual(set(result['granted']), expected_perms)

    def test_multiple_groups_permissions_accumulate(self):
        """Test that permissions accumulate across multiple groups"""
        # User is admin in group1
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        # User is member in group2
        GroupMembership.objects.create(
            group=self.group2,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['member'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        # Should have permissions from both groups
        self.assertIn('test-group-1', result['groups'])
        self.assertIn('test-group-2', result['groups'])

        # Global permissions should be union
        admin_perms = set(ROLE_PERMISSIONS['admin'])
        member_perms = set(ROLE_PERMISSIONS['member'])
        expected_global = admin_perms | member_perms
        self.assertEqual(set(result['granted']), expected_global)

        # Group1 should have admin perms
        self.assertEqual(set(result['groups']['test-group-1']['permissions']), admin_perms)

        # Group2 should have member perms
        self.assertEqual(set(result['groups']['test-group-2']['permissions']), member_perms)

    def test_inactive_membership_excluded(self):
        """Test that inactive memberships don't grant permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=False,  # Inactive
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        self.assertEqual(result['granted'], [])
        self.assertEqual(result['groups'], {})

    def test_pending_membership_excluded(self):
        """Test that pending memberships don't grant permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=True  # Pending
        )

        result = PermissionService.compute_user_permissions(self.user1)

        self.assertEqual(result['granted'], [])
        self.assertEqual(result['groups'], {})

    def test_banned_membership_excluded(self):
        """Test that banned memberships don't grant permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False,
            is_banned=True  # Banned
        )

        result = PermissionService.compute_user_permissions(self.user1)

        self.assertEqual(result['granted'], [])
        self.assertEqual(result['groups'], {})

    def test_evicted_membership_excluded(self):
        """Test that evicted memberships don't grant permissions"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False,
            is_evicted=True  # Evicted
        )

        result = PermissionService.compute_user_permissions(self.user1)

        self.assertEqual(result['granted'], [])
        self.assertEqual(result['groups'], {})

    def test_can_user_perform_action_global(self):
        """Test can_user_perform_action without group_slug (global check)"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['coordinator'],
            is_active=True,
            is_pending=False
        )

        # User should be able to create course globally
        self.assertTrue(
            PermissionService.can_user_perform_action(self.user1, 'create_course')
        )

        # User should NOT be able to publish course globally
        self.assertFalse(
            PermissionService.can_user_perform_action(self.user1, 'publish_course')
        )

    def test_can_user_perform_action_in_specific_group(self):
        """Test can_user_perform_action with group_slug (group-specific check)"""
        # User is admin in group1
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        # User is member in group2
        GroupMembership.objects.create(
            group=self.group2,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['member'],
            is_active=True,
            is_pending=False
        )

        # Can create course in group1 (admin)
        self.assertTrue(
            PermissionService.can_user_perform_action(
                self.user1, 'create_course', 'test-group-1'
            )
        )

        # CANNOT create course in group2 (member)
        self.assertFalse(
            PermissionService.can_user_perform_action(
                self.user1, 'create_course', 'test-group-2'
            )
        )

    def test_can_user_perform_action_no_membership_in_group(self):
        """Test checking permission in a group where user has no membership"""
        # User has no membership in group1
        self.assertFalse(
            PermissionService.can_user_perform_action(
                self.user1, 'create_course', 'test-group-1'
            )
        )

    def test_superuser_has_all_permissions(self):
        """Test that superusers always have all permissions"""
        # Superuser has no memberships
        self.assertTrue(
            PermissionService.can_user_perform_action(
                self.superuser, 'create_course'
            )
        )

        self.assertTrue(
            PermissionService.can_user_perform_action(
                self.superuser, 'delete_course', 'test-group-1'
            )
        )

    def test_get_user_permissions_in_group(self):
        """Test get_user_permissions_in_group method"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['steward'],
            is_active=True,
            is_pending=False
        )

        perms = PermissionService.get_user_permissions_in_group(
            self.user1, 'test-group-1'
        )

        steward_perms = ROLE_PERMISSIONS['steward']
        self.assertEqual(set(perms), set(steward_perms))

    def test_get_user_permissions_in_group_no_membership(self):
        """Test get_user_permissions_in_group when user has no membership"""
        perms = PermissionService.get_user_permissions_in_group(
            self.user1, 'test-group-1'
        )

        self.assertEqual(perms, [])

    def test_get_user_roles_in_group(self):
        """Test get_user_roles_in_group method"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin', 'steward'],
            is_active=True,
            is_pending=False
        )

        roles = PermissionService.get_user_roles_in_group(
            self.user1, 'test-group-1'
        )

        # The save() method automatically adds 'member' if not present
        self.assertEqual(set(roles), {'member', 'admin', 'steward'})

    def test_get_user_roles_in_group_no_membership(self):
        """Test get_user_roles_in_group when user has no membership"""
        roles = PermissionService.get_user_roles_in_group(
            self.user1, 'test-group-1'
        )

        self.assertEqual(roles, [])

    def test_convenience_function_can_create_course(self):
        """Test can_create_course convenience function"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['coordinator'],
            is_active=True,
            is_pending=False
        )

        self.assertTrue(can_create_course(self.user1, 'test-group-1'))
        self.assertFalse(can_create_course(self.user1, 'test-group-2'))

    def test_convenience_function_can_manage_members(self):
        """Test can_manage_members convenience function"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        self.assertTrue(can_manage_members(self.user1, 'test-group-1'))

        # Coordinator cannot manage members
        GroupMembership.objects.create(
            group=self.group2,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['coordinator'],
            is_active=True,
            is_pending=False
        )

        self.assertFalse(can_manage_members(self.user1, 'test-group-2'))

    def test_convenience_function_can_edit_group(self):
        """Test can_edit_group convenience function"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        self.assertTrue(can_edit_group(self.user1, 'test-group-1'))

        # Member cannot edit group
        GroupMembership.objects.create(
            group=self.group2,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['member'],
            is_active=True,
            is_pending=False
        )

        self.assertFalse(can_edit_group(self.user1, 'test-group-2'))

    def test_unknown_role_grants_no_permissions(self):
        """Test that unknown/invalid roles don't grant permissions (except auto-added 'member' role)"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=['unknown_role', 'invalid_role'],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        # Should only have 'member' permissions (auto-added by save method)
        member_perms = set(ROLE_PERMISSIONS['member'])
        self.assertEqual(set(result['granted']), member_perms)
        self.assertEqual(set(result['groups']['test-group-1']['permissions']), member_perms)

    def test_empty_roles_list_grants_no_permissions(self):
        """Test that empty roles list gets auto-assigned 'member' role"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=[],
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        # Empty roles list gets auto-assigned 'member' role by save() method
        member_perms = set(ROLE_PERMISSIONS['member'])
        self.assertEqual(set(result['granted']), member_perms)
        self.assertEqual(set(result['groups']['test-group-1']['permissions']), member_perms)

    def test_null_roles_grants_no_permissions(self):
        """Test that null roles gets auto-assigned 'member' role"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user1.id,
            roles=None,
            is_active=True,
            is_pending=False
        )

        result = PermissionService.compute_user_permissions(self.user1)

        # Null roles gets auto-assigned 'member' role by save() method
        member_perms = set(ROLE_PERMISSIONS['member'])
        self.assertEqual(set(result['granted']), member_perms)
        self.assertEqual(set(result['groups']['test-group-1']['permissions']), member_perms)
