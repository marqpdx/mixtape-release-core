# fundamentals/api/views.py
"""
API views for Phase 4 Workbench (Review Queue, MillDrafts).
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from fundamentals.models import (
    MillDraft,
    MillDraftStatus,
    ContentProfileConfig,
    ReviewQueueEntry,
    ReviewQueueDecision,
)
from fundamentals.services.draft_promotion import (
    promote_draft,
    PromotionError,
    ValidationError as DraftValidationError,
    PSCViolation,
    UnsupportedProfile,
)
from .serializers import (
    MillDraftListSerializer,
    MillDraftDetailSerializer,
    MillDraftCreateSerializer,
    MillDraftUpdateSerializer,
    MillDraftActionSerializer,
    ContentProfileConfigSerializer,
)


class MillDraftViewSet(viewsets.ModelViewSet):
    """
    ViewSet for MillDraft CRUD and Review Queue.

    Endpoints:
    - GET /api/workbench/drafts - List drafts (Review Queue)
    - POST /api/workbench/drafts - Create new draft
    - GET /api/workbench/drafts/{id} - Get draft detail
    - PATCH /api/workbench/drafts/{id} - Update draft
    - POST /api/workbench/drafts/{id}/actions - Apply action (discard/approve/promote/etc.)
    - GET /api/workbench/queue - Review Queue (candidates only)
    """

    permission_classes = [IsAuthenticated]
    queryset = MillDraft.objects.all()
    lookup_field = 'pk'
    lookup_value_regex = '[0-9a-fA-F-]+'

    @staticmethod
    def _user_can_access_sponsor(user, sponsor_ct, sponsor_object_id):
        """
        Return True if user has read access to the given sponsor's drafts.

        - User-sponsored: request.user must be the sponsor.
        - Group-sponsored: request.user must be an active member (any role).
        """
        from django.contrib.auth import get_user_model
        from groups.models import Group, GroupMembership

        User = get_user_model()
        user_ct = ContentType.objects.get_for_model(User)

        if sponsor_ct == user_ct:
            return str(user.id) == str(sponsor_object_id)

        group_ct = ContentType.objects.get_for_model(Group)
        if sponsor_ct == group_ct:
            return GroupMembership.objects.filter(
                group_id=sponsor_object_id,
                member_content_type=user_ct,
                member_object_id=user.id,
                deleted_at__isnull=True,
            ).exists()

        return False

    @staticmethod
    def _user_has_steward_access(user, sponsor_ct, sponsor_object_id):
        """
        Return True if user has steward-level access to the given sponsor.

        Required for all triage actions (open, discard, approve, promote,
        archive, reactivate). Steward, admin, and owner all qualify.

        - User-sponsored: request.user must be the sponsor (they are the owner).
        - Group-sponsored: membership must include steward, admin, or owner role.
        """
        from django.contrib.auth import get_user_model
        from groups.models import Group, GroupMembership

        User = get_user_model()
        user_ct = ContentType.objects.get_for_model(User)

        if sponsor_ct == user_ct:
            return str(user.id) == str(sponsor_object_id)

        group_ct = ContentType.objects.get_for_model(Group)
        if sponsor_ct == group_ct:
            return GroupMembership.objects.filter(
                group_id=sponsor_object_id,
                member_content_type=user_ct,
                member_object_id=user.id,
                deleted_at__isnull=True,
                roles__overlap=['steward', 'admin', 'owner'],
            ).exists()

        return False

    def check_object_permissions(self, request, obj):
        """Enforce sponsor membership for all detail-level operations."""
        super().check_object_permissions(request, obj)
        if not self._user_can_access_sponsor(
            request.user,
            obj.sponsor_content_type,
            obj.sponsor_object_id,
        ):
            raise PermissionDenied("You do not have access to this draft.")

    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list' or self.action == 'queue':
            return MillDraftListSerializer
        elif self.action == 'create':
            return MillDraftCreateSerializer
        elif self.action == 'partial_update' or self.action == 'update':
            return MillDraftUpdateSerializer
        elif self.action == 'perform_action':
            return MillDraftActionSerializer
        else:
            return MillDraftDetailSerializer

    def get_queryset(self):
        """
        Filter drafts by sponsor context.

        Query params:
        - sponsor_type: user|group (required for list/queue)
        - sponsor_id: UUID (required for list/queue)
        - status: candidate|active|ready_to_promote|archived
        - content_profile: event|writing|course|etc.
        - source_type: stackroom|concord|gristmill|etc.
        """
        queryset = MillDraft.objects.select_related(
            'author',
            'submitted_by',
            'sponsor_content_type',
            'canonical_content_type'
        )

        # For detail views (when pk is in URL), don't require sponsor filtering
        # This allows direct UUID lookups to work for retrieve, update, and custom actions
        if self.kwargs.get('pk'):
            return queryset.filter(deleted_at__isnull=True)

        # Filter by sponsor (required for list/queue views)
        sponsor_type = self.request.query_params.get('sponsor_type')
        sponsor_id = self.request.query_params.get('sponsor_id')

        if not sponsor_type or not sponsor_id:
            # Return empty queryset if sponsor not specified for list views
            return queryset.none()

        # Get ContentType for sponsor
        if sponsor_type == 'user':
            from django.contrib.auth import get_user_model
            User = get_user_model()
            sponsor_ct = ContentType.objects.get_for_model(User)
        elif sponsor_type == 'group':
            from groups.models import Group
            sponsor_ct = ContentType.objects.get_for_model(Group)
        else:
            return queryset.none()

        # Enforce sponsor membership before returning any data
        if not self._user_can_access_sponsor(self.request.user, sponsor_ct, sponsor_id):
            raise PermissionDenied("You do not have access to this sponsor's drafts.")

        queryset = queryset.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id
        )

        # Exclude soft-deleted
        queryset = queryset.filter(deleted_at__isnull=True)

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Filter by content profile
        profile = self.request.query_params.get('content_profile')
        if profile:
            queryset = queryset.filter(content_profile=profile)

        # Filter by source type
        source = self.request.query_params.get('source_type')
        if source:
            queryset = queryset.filter(source_type=source)

        # Order by newest first
        queryset = queryset.order_by('-created_at')

        return queryset

    def create(self, request, *args, **kwargs):
        """Create new MillDraft"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Set submitted_by to current user
        draft = serializer.save(submitted_by=request.user)

        # Return detailed representation
        detail_serializer = MillDraftDetailSerializer(draft)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        """Update MillDraft (editing)"""
        instance = self.get_object()

        # Only allow editing active drafts
        if not instance.is_active:
            return Response(
                {'error': 'Only active drafts can be edited'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        draft = serializer.save()

        # Return detailed representation
        detail_serializer = MillDraftDetailSerializer(draft)
        return Response(detail_serializer.data)

    @action(detail=False, methods=['get'])
    def queue(self, request):
        """
        Review Queue endpoint - candidates only.

        GET /api/workbench/queue?sponsor_type=group&sponsor_id=<uuid>
        """
        # Filter to candidates only
        queryset = self.get_queryset().filter(status=MillDraftStatus.CANDIDATE)

        # Paginate
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = MillDraftListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = MillDraftListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='perform-action', url_name='perform-action')
    def perform_action(self, request, pk=None):
        """
        Perform action on draft.

        POST /api/workbench/drafts/{id}/perform-action
        Body: {"action": "discard|approve|open|promote|archive|reactivate"}
        """
        draft = self.get_object()

        # Triage actions require steward+ role
        if not self._user_has_steward_access(
            request.user,
            draft.sponsor_content_type,
            draft.sponsor_object_id,
        ):
            raise PermissionDenied("Triage actions require steward role or higher.")

        serializer = MillDraftActionSerializer(
            data=request.data,
            context={'draft': draft}
        )
        serializer.is_valid(raise_exception=True)

        action_name = serializer.validated_data['action']
        notes = serializer.validated_data.get('notes', '')

        # Map action names to ReviewQueueDecision values (audit log)
        _AUDIT_DECISION = {
            'discard': ReviewQueueDecision.DISCARD,
            'approve': ReviewQueueDecision.APPROVE,
            'archive': ReviewQueueDecision.ARCHIVE,
        }

        try:
            if action_name == 'discard':
                draft.soft_delete(user=request.user)
                message = 'Draft discarded'

            elif action_name == 'approve':
                # Approve for Consideration — no state change, just audit record
                message = 'Draft approved for consideration'

            elif action_name == 'open':
                # Open for editing (candidate → active) — intentionally not audited
                draft.open_for_editing(user=request.user)
                message = 'Draft opened for editing'

            elif action_name == 'promote':
                publish = serializer.validated_data.get('publish', False)
                try:
                    result = promote_draft(
                        draft=draft,
                        promoted_by=request.user,
                        publish=publish,
                    )
                    draft.refresh_from_db()
                    message = (
                        f"Draft promoted to {result.canonical_type}"
                        + (" and published" if result.was_published else " as draft")
                    )
                    ReviewQueueEntry.objects.create(
                        draft=draft,
                        decision=(
                            ReviewQueueDecision.PROMOTE_AND_PUBLISH
                            if result.was_published
                            else ReviewQueueDecision.PROMOTE
                        ),
                        decided_by=request.user,
                        notes=notes,
                    )
                except DraftValidationError as exc:
                    return Response(
                        {'error': str(exc), 'validation_errors': exc.validation_errors},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                except (PSCViolation, UnsupportedProfile, PromotionError) as exc:
                    return Response(
                        {'error': str(exc)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            elif action_name == 'archive':
                draft.archive(user=request.user)
                message = 'Draft archived'

            elif action_name == 'reactivate':
                # Reactivate archived draft — not a queue decision, no audit entry
                draft.reactivate(user=request.user)
                message = 'Draft reactivated'

            else:
                return Response(
                    {'error': f'Unknown action: {action_name}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Write audit entry for queue-surface decisions (discard/approve/archive)
            if action_name in _AUDIT_DECISION:
                ReviewQueueEntry.objects.create(
                    draft=draft,
                    decision=_AUDIT_DECISION[action_name],
                    decided_by=request.user,
                    notes=notes,
                )

            detail_serializer = MillDraftDetailSerializer(draft)
            return Response({
                'message': message,
                'draft': detail_serializer.data
            })

        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
        """
        Run validation on draft.

        POST /api/workbench/drafts/{id}/validate
        Body: {"hard": true|false}
        """
        draft = self.get_object()
        hard = request.data.get('hard', False)

        validation_result = draft.run_validation(hard=hard)

        return Response({
            'is_valid': draft.is_valid,
            'validation_state': validation_result,
            'errors': draft.validation_errors,
            'warnings': draft.validation_warnings,
        })


class ContentProfileConfigViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Content Profile Configuration (read-only).

    Endpoints:
    - GET /api/workbench/profiles - List enabled profiles
    - GET /api/workbench/profiles/{name} - Get profile config
    """

    permission_classes = [IsAuthenticated]
    queryset = ContentProfileConfig.objects.filter(is_enabled=True)
    serializer_class = ContentProfileConfigSerializer
    lookup_field = 'profile_name'

    def get_queryset(self):
        """Return enabled profiles only"""
        return ContentProfileConfig.objects.filter(is_enabled=True).order_by('profile_name')
