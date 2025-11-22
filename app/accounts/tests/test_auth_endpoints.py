"""
Integration tests for auth endpoints with permissions

Tests that auth endpoints correctly compute and return permissions data.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from groups.models import Group, GroupMembership
from groups.services.permissions import ROLE_PERMISSIONS

User = get_user_model()


class AuthEndpointsPermissionsTestCase(APITestCase):
    """Test suite for auth endpoints with permissions integration"""

    def setUp(self):
        """Create test fixtures"""
        self.client = APIClient()

        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

        # Create test groups
        self.group1 = Group.objects.create(
            title='Education Hub',
            slug='education-hub',
            description='Test education group',
            group_type='community',
            decorators=[],
            additional_permissions=[]
        )
        self.group2 = Group.objects.create(
            title='Community Center',
            slug='community-center',
            description='Test community group',
            group_type='community',
            decorators=[],
            additional_permissions=[]
        )

        # Get user content type
        self.user_ct = ContentType.objects.get_for_model(User)

    def test_login_returns_permissions_data(self):
        """Test that login endpoint returns permissions in response"""
        # Create admin membership for user
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        # Login
        url = reverse('token-login')
        response = self.client.post(url, {
            'identifier': 'testuser',
            'password': 'testpass123'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check permissions in response
        self.assertIn('permissions', response.data)
        permissions = response.data['permissions']

        # Verify structure
        self.assertIn('granted', permissions)
        self.assertIn('effective', permissions)
        self.assertIn('groups', permissions)

        # Verify permissions content
        admin_perms = set(ROLE_PERMISSIONS['admin'])
        self.assertEqual(set(permissions['granted']), admin_perms)
        self.assertEqual(set(permissions['effective']), admin_perms)

        # Verify group-specific data
        self.assertIn('education-hub', permissions['groups'])
        group_data = permissions['groups']['education-hub']
        # The save() method automatically adds 'member' if not present
        self.assertEqual(set(group_data['roles']), {'member', 'admin'})
        self.assertEqual(set(group_data['permissions']), admin_perms)

    def test_login_without_memberships_returns_empty_permissions(self):
        """Test that login returns empty permissions for users with no memberships"""
        # Login user with no group memberships
        url = reverse('token-login')
        response = self.client.post(url, {
            'identifier': 'testuser',
            'password': 'testpass123'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check permissions are empty but structured correctly
        permissions = response.data['permissions']
        self.assertEqual(permissions['granted'], [])
        self.assertEqual(permissions['effective'], [])
        self.assertEqual(permissions['groups'], {})

    def test_login_with_multiple_groups_returns_accumulated_permissions(self):
        """Test that login returns accumulated permissions from multiple groups"""
        # User is admin in group1
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        # User is member in group2
        GroupMembership.objects.create(
            group=self.group2,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['member'],
            is_active=True,
            is_pending=False
        )

        # Login
        url = reverse('token-login')
        response = self.client.post(url, {
            'identifier': 'testuser',
            'password': 'testpass123'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        permissions = response.data['permissions']

        # Should have permissions from both groups
        admin_perms = set(ROLE_PERMISSIONS['admin'])
        member_perms = set(ROLE_PERMISSIONS['member'])
        expected_global = admin_perms | member_perms

        self.assertEqual(set(permissions['granted']), expected_global)

        # Verify both groups present
        self.assertIn('education-hub', permissions['groups'])
        self.assertIn('community-center', permissions['groups'])

        # Verify group-specific permissions
        self.assertEqual(
            set(permissions['groups']['education-hub']['permissions']),
            admin_perms
        )
        self.assertEqual(
            set(permissions['groups']['community-center']['permissions']),
            member_perms
        )

    def test_auth_me_endpoint_returns_permissions(self):
        """Test that /auth/me endpoint includes permissions"""
        # Create membership
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['steward'],
            is_active=True,
            is_pending=False
        )

        # Authenticate
        self.client.force_authenticate(user=self.user)

        # Get current user identity
        url = reverse('current-user-identity')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify permissions in response
        self.assertIn('permissions', response.data)
        permissions = response.data['permissions']

        steward_perms = set(ROLE_PERMISSIONS['steward'])
        self.assertEqual(set(permissions['granted']), steward_perms)

    def test_auth_me_endpoint_unauthenticated(self):
        """Test that /auth/me returns 401 for unauthenticated requests"""
        url = reverse('current-user-identity')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_permissions_refresh_endpoint(self):
        """Test that /auth/permissions/refresh returns updated permissions"""
        # Create initial membership
        membership = GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['member'],
            is_active=True,
            is_pending=False
        )

        # Authenticate
        self.client.force_authenticate(user=self.user)

        # Get permissions
        url = reverse('refresh-permissions')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify initial member permissions
        member_perms = set(ROLE_PERMISSIONS['member'])
        self.assertEqual(set(response.data['granted']), member_perms)

        # Upgrade role to admin
        membership.roles = ['admin']
        membership.save()

        # Refresh permissions
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify updated admin permissions
        admin_perms = set(ROLE_PERMISSIONS['admin'])
        self.assertEqual(set(response.data['granted']), admin_perms)

    def test_permissions_refresh_endpoint_unauthenticated(self):
        """Test that permissions refresh requires authentication"""
        url = reverse('refresh-permissions')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_permissions_update_when_membership_deactivated(self):
        """Test that deactivating membership removes permissions on refresh"""
        # Create active membership
        membership = GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        # Authenticate
        self.client.force_authenticate(user=self.user)

        # Get initial permissions
        url = reverse('refresh-permissions')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data['granted']) > 0)

        # Deactivate membership
        membership.is_active = False
        membership.save()

        # Refresh permissions
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Permissions should now be empty
        self.assertEqual(response.data['granted'], [])
        self.assertEqual(response.data['groups'], {})

    def test_permissions_update_when_membership_banned(self):
        """Test that banning membership removes permissions on refresh"""
        # Create active membership
        membership = GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        # Authenticate
        self.client.force_authenticate(user=self.user)

        # Get initial permissions
        url = reverse('refresh-permissions')
        response = self.client.get(url)
        self.assertTrue(len(response.data['granted']) > 0)

        # Ban user
        membership.is_banned = True
        membership.save()

        # Refresh permissions
        response = self.client.get(url)
        self.assertEqual(response.data['granted'], [])

    def test_permissions_with_multiple_roles_in_one_group(self):
        """Test permissions when user has multiple roles in one group"""
        # Create membership with multiple roles
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['coordinator', 'member'],
            is_active=True,
            is_pending=False
        )

        # Authenticate
        self.client.force_authenticate(user=self.user)

        # Get permissions
        url = reverse('refresh-permissions')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have union of both roles
        coordinator_perms = set(ROLE_PERMISSIONS['coordinator'])
        member_perms = set(ROLE_PERMISSIONS['member'])
        expected = coordinator_perms | member_perms

        self.assertEqual(set(response.data['granted']), expected)

    def test_login_with_email(self):
        """Test login with email instead of username"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        url = reverse('token-login')
        response = self.client.post(url, {
            'identifier': 'test@example.com',  # Using email
            'password': 'testpass123'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('permissions', response.data)
        self.assertTrue(len(response.data['permissions']['granted']) > 0)

    def test_permissions_include_all_expected_fields(self):
        """Test that permissions response has all required fields"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        self.client.force_authenticate(user=self.user)

        url = reverse('refresh-permissions')
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify top-level fields
        self.assertIn('granted', response.data)
        self.assertIn('effective', response.data)
        self.assertIn('groups', response.data)

        # Verify granted is a list
        self.assertIsInstance(response.data['granted'], list)

        # Verify effective is a list
        self.assertIsInstance(response.data['effective'], list)

        # Verify groups is a dict
        self.assertIsInstance(response.data['groups'], dict)

        # Verify group structure
        group_data = response.data['groups']['education-hub']
        self.assertIn('roles', group_data)
        self.assertIn('permissions', group_data)
        self.assertIsInstance(group_data['roles'], list)
        self.assertIsInstance(group_data['permissions'], list)

    def test_permissions_sorted_consistently(self):
        """Test that permissions are returned in sorted order for consistency"""
        GroupMembership.objects.create(
            group=self.group1,
            member_content_type=self.user_ct,
            member_object_id=self.user.id,
            roles=['admin'],
            is_active=True,
            is_pending=False
        )

        self.client.force_authenticate(user=self.user)

        url = reverse('refresh-permissions')

        # Call multiple times
        response1 = self.client.get(url)
        response2 = self.client.get(url)

        # Results should be identical and sorted
        self.assertEqual(response1.data['granted'], response2.data['granted'])
        self.assertEqual(
            response1.data['granted'],
            sorted(response1.data['granted'])
        )


class DRFPermissionClassesTestCase(APITestCase):
    """Test suite for DRF permission classes (stub for future implementation)"""

    def setUp(self):
        """Setup test fixtures"""
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.group = Group.objects.create(
            title='Test Group',
            slug='test-group',
            description='Test group for permissions',
            group_type='community',
            decorators=[],
            additional_permissions=[]
        )
        self.user_ct = ContentType.objects.get_for_model(User)

    def test_permission_classes_placeholder(self):
        """
        Placeholder test for DRF permission classes.

        TODO: Once you have API endpoints using HasPermission classes,
        add tests here to verify they protect views correctly.

        Example tests to add:
        - Test that users without 'create_course' permission cannot access create course endpoint
        - Test that users with 'manage_members' can access member management endpoints
        - Test that superusers bypass permission checks
        """
        self.assertTrue(True)  # Placeholder
