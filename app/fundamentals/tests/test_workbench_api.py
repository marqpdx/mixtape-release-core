# fundamentals/tests/test_workbench_api.py
"""
Integration tests for Phase 4 Workbench API (Review Queue, MillDrafts).
"""

import uuid
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from fundamentals.models import MillDraft, MillDraftStatus, ContentProfileConfig
from groups.models import Group


User = get_user_model()


class WorkbenchAPITestCase(TestCase):
    """Base test case with common setup"""

    def setUp(self):
        """Create test users and group"""
        self.client = APIClient()

        # Create users
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@test.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@test.com',
            password='testpass123'
        )

        # Create test group (sponsor = user1)
        self.group = Group.objects.create(
            title='Test Group',
            slug='test-group',
            description='Test group for Workbench API',
            group_type='community',
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.user1.id
        )

        # Create content profile config
        self.profile_config = ContentProfileConfig.objects.create(
            profile_name='event',
            display_name='Event',
            description='Event profile for testing',
            publish_safety_class='psc_1',
            required_fields=['title', 'summary'],
            is_enabled=True
        )

        # Get ContentType for group
        self.group_ct = ContentType.objects.get_for_model(Group)

    def authenticate(self, user=None):
        """Authenticate client as user"""
        if user is None:
            user = self.user1
        self.client.force_authenticate(user=user)


class MillDraftCreateTestCase(WorkbenchAPITestCase):
    """Test creating MillDrafts"""

    def test_create_milldraft_success(self):
        """Test successful MillDraft creation"""
        self.authenticate()

        data = {
            'sponsor_type': 'group',
            'sponsor_id': str(self.group.id),
            'content_profile': 'event',
            'title': 'Test Event',
            'summary': 'Test event summary',
            'grist_body': 'Test event grist content',
            'source_type': 'manual',
            'source_id': 'test-source-1',
        }

        response = self.client.post('/api/workbench/drafts/', data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['title'], 'Test Event')
        self.assertEqual(response.data['status'], MillDraftStatus.CANDIDATE)
        self.assertEqual(response.data['content_profile'], 'event')
        self.assertEqual(response.data['sponsor_type'], 'group')

        # Verify in database
        draft = MillDraft.objects.get(id=response.data['id'])
        self.assertEqual(draft.title, 'Test Event')
        self.assertEqual(draft.sponsor_object_id, self.group.id)
        self.assertEqual(draft.submitted_by, self.user1)

    def test_create_milldraft_requires_auth(self):
        """Test that creating MillDraft requires authentication"""
        data = {
            'sponsor_type': 'group',
            'sponsor_id': str(self.group.id),
            'content_profile': 'event',
            'title': 'Test Event',
        }

        response = self.client.post('/api/workbench/drafts/', data, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ReviewQueueTestCase(WorkbenchAPITestCase):
    """Test Review Queue API"""

    def setUp(self):
        super().setUp()

        # Create some test drafts
        self.draft1 = MillDraft.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            content_profile='event',
            title='Draft 1',
            summary='Summary 1',
            status=MillDraftStatus.CANDIDATE,
            source_type='stackroom',
            source_id='artifact-1',
            submitted_by=self.user1
        )

        self.draft2 = MillDraft.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            content_profile='event',
            title='Draft 2',
            summary='Summary 2',
            status=MillDraftStatus.CANDIDATE,
            source_type='concord',
            source_id='recording-1',
            submitted_by=self.user1
        )

        self.draft3 = MillDraft.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            content_profile='event',
            title='Draft 3 Active',
            summary='Summary 3',
            status=MillDraftStatus.ACTIVE,
            source_type='manual',
            source_id='manual-1',
            submitted_by=self.user2
        )

    def test_review_queue_list_candidates(self):
        """Test Review Queue lists candidates only"""
        self.authenticate()

        response = self.client.get(
            '/api/workbench/drafts/queue/',
            {'sponsor_type': 'group', 'sponsor_id': str(self.group.id)}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Handle both paginated and non-paginated responses
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertEqual(len(results), 2)  # Only candidates

        titles = [item['title'] for item in results]
        self.assertIn('Draft 1', titles)
        self.assertIn('Draft 2', titles)
        self.assertNotIn('Draft 3 Active', titles)

    def test_review_queue_requires_sponsor_params(self):
        """Test Review Queue requires sponsor params"""
        self.authenticate()

        response = self.client.get('/api/workbench/drafts/queue/')

        # Should return empty when sponsor not specified
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertEqual(len(results), 0)

    def test_list_drafts_with_filters(self):
        """Test listing drafts with status and source filters"""
        self.authenticate()

        # Filter by status
        response = self.client.get(
            '/api/workbench/drafts/',
            {
                'sponsor_type': 'group',
                'sponsor_id': str(self.group.id),
                'status': MillDraftStatus.ACTIVE
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Draft 3 Active')

        # Filter by source type
        response = self.client.get(
            '/api/workbench/drafts/',
            {
                'sponsor_type': 'group',
                'sponsor_id': str(self.group.id),
                'source_type': 'stackroom'
            }
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Draft 1')


class MillDraftActionsTestCase(WorkbenchAPITestCase):
    """Test MillDraft actions (open, promote, archive, etc.)"""

    def setUp(self):
        super().setUp()

        # Create test draft
        self.draft = MillDraft.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            content_profile='event',
            title='Test Draft',
            summary='Test summary',
            grist_body='Test content',
            status=MillDraftStatus.CANDIDATE,
            source_type='manual',
            source_id='test-1',
            submitted_by=self.user1
        )

    def test_action_open_draft(self):
        """Test opening a candidate draft for editing"""
        self.authenticate()

        response = self.client.post(
            f'/api/workbench/drafts/{self.draft.id}/perform-action/',
            {'action': 'open'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Draft opened for editing')
        self.assertEqual(response.data['draft']['status'], MillDraftStatus.ACTIVE)

        # Verify in database
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, MillDraftStatus.ACTIVE)

    def test_action_archive_draft(self):
        """Test archiving a draft"""
        self.authenticate()

        response = self.client.post(
            f'/api/workbench/drafts/{self.draft.id}/perform-action/',
            {'action': 'archive'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Draft archived')
        self.assertEqual(response.data['draft']['status'], MillDraftStatus.ARCHIVED)

        # Verify in database
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, MillDraftStatus.ARCHIVED)
        self.assertIsNotNone(self.draft.archived_at)
        self.assertEqual(self.draft.archived_by, self.user1)

    def test_action_discard_draft(self):
        """Test discarding a draft (soft delete)"""
        self.authenticate()

        response = self.client.post(
            f'/api/workbench/drafts/{self.draft.id}/perform-action/',
            {'action': 'discard'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'Draft discarded')

        # Verify in database (soft deleted)
        self.draft.refresh_from_db()
        self.assertIsNotNone(self.draft.deleted_at)
        self.assertEqual(self.draft.deleted_by, self.user1)

    def test_action_promote_requires_validation(self):
        """Test that promotion requires valid draft"""
        self.authenticate()

        # Try to promote candidate (should fail - not ready)
        response = self.client.post(
            f'/api/workbench/drafts/{self.draft.id}/perform-action/',
            {'action': 'promote'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # DRF serializer errors use 'non_field_errors' or 'detail' key
        error_msg = str(response.data.get('non_field_errors', response.data.get('detail', '')))
        self.assertIn('ready', error_msg.lower())

    def test_action_invalid_state_transition(self):
        """Test invalid state transition"""
        self.authenticate()

        # Try to reactivate a candidate (invalid)
        response = self.client.post(
            f'/api/workbench/drafts/{self.draft.id}/perform-action/',
            {'action': 'reactivate'},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MillDraftUpdateTestCase(WorkbenchAPITestCase):
    """Test updating MillDrafts"""

    def setUp(self):
        super().setUp()

        # Create active draft
        self.draft = MillDraft.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            content_profile='event',
            title='Original Title',
            summary='Original summary',
            grist_body='Original content',
            status=MillDraftStatus.ACTIVE,  # Active for editing
            source_type='manual',
            source_id='test-1',
            submitted_by=self.user1
        )

    def test_update_draft_success(self):
        """Test successful draft update"""
        self.authenticate()

        data = {
            'title': 'Updated Title',
            'summary': 'Updated summary',
            'grist_body': 'Updated content'
        }

        response = self.client.patch(
            f'/api/workbench/drafts/{self.draft.id}/',
            data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Title')

        # Verify in database
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.title, 'Updated Title')
        self.assertEqual(self.draft.summary, 'Updated summary')

    def test_update_only_active_drafts(self):
        """Test that only active drafts can be edited"""
        self.authenticate()

        # Archive the draft
        self.draft.archive(user=self.user1)

        data = {'title': 'Updated Title'}
        response = self.client.patch(
            f'/api/workbench/drafts/{self.draft.id}/',
            data,
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('active', response.data['error'].lower())


class MillDraftValidationTestCase(WorkbenchAPITestCase):
    """Test MillDraft validation"""

    def setUp(self):
        super().setUp()

        # Create draft for validation testing
        self.draft = MillDraft.objects.create(
            sponsor_content_type=self.group_ct,
            sponsor_object_id=self.group.id,
            content_profile='event',
            title='',  # Empty title (will fail validation)
            summary='Test summary',
            grist_body='Test content',
            status=MillDraftStatus.ACTIVE,
            source_type='manual',
            source_id='test-1',
            submitted_by=self.user1
        )

    def test_validation_endpoint(self):
        """Test validation endpoint"""
        self.authenticate()

        response = self.client.post(
            f'/api/workbench/drafts/{self.draft.id}/validate/',
            {'hard': True},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_valid'])
        self.assertGreater(len(response.data['errors']), 0)

        # Check that title error is present
        error_fields = [err['field'] for err in response.data['errors']]
        self.assertIn('title', error_fields)


class ContentProfileConfigTestCase(WorkbenchAPITestCase):
    """Test Content Profile Configuration API"""

    def test_list_profiles(self):
        """Test listing enabled profiles"""
        self.authenticate()

        response = self.client.get('/api/workbench/profiles/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        self.assertGreaterEqual(len(results), 1)  # At least one profile (the one we created)

        # Check that our test profile is in the results
        profile_names = [p['profile_name'] for p in results]
        self.assertIn('event', profile_names)

    def test_get_profile_detail(self):
        """Test getting profile configuration"""
        self.authenticate()

        response = self.client.get('/api/workbench/profiles/event/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['profile_name'], 'event')
        self.assertEqual(response.data['publish_safety_class'], 'psc_1')
        self.assertEqual(response.data['required_fields'], ['title', 'summary'])
