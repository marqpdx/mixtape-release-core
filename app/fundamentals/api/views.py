# fundamentals/api/views.py
"""
API views for Phase 4 Workbench (Review Queue, MillDrafts).
"""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from fundamentals.models import MillDraft, MillDraftStatus, ContentProfileConfig
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
        serializer = MillDraftActionSerializer(
            data=request.data,
            context={'draft': draft}
        )
        serializer.is_valid(raise_exception=True)

        action_name = serializer.validated_data['action']

        try:
            if action_name == 'discard':
                # Discard = soft delete
                draft.soft_delete(user=request.user)
                message = 'Draft discarded'

            elif action_name == 'approve':
                # Approve for Consideration (no state change, just a marker)
                # For now, just return success
                # TODO: Add approval tracking if needed
                message = 'Draft approved for consideration'

            elif action_name == 'open':
                # Open for editing (candidate → active)
                draft.open_for_editing(user=request.user)
                message = 'Draft opened for editing'

            elif action_name == 'promote':
                # Run hard validation
                validation_result = draft.run_validation(hard=True)
                if not draft.is_valid:
                    return Response(
                        {
                            'error': 'Draft failed validation',
                            'validation_errors': draft.validation_errors
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Mark ready to promote
                if draft.is_active:
                    draft.mark_ready_to_promote()

                # Promote
                draft.promote(user=request.user)
                message = 'Draft promoted successfully'

                # TODO: Actually create/update canonical object here
                # For now, just mark as promoted

            elif action_name == 'archive':
                # Archive draft
                draft.archive(user=request.user)
                message = 'Draft archived'

            elif action_name == 'reactivate':
                # Reactivate archived draft
                draft.reactivate(user=request.user)
                message = 'Draft reactivated'

            else:
                return Response(
                    {'error': f'Unknown action: {action_name}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Return updated draft
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
