# almanac/api/views.py

"""
Mixtape Almanac API Views (Refactored)
Explicit, polymorphic views following threadworks pattern
Shared logic in mixins, concrete implementations for each context
"""

from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.db import transaction, models
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from datetime import datetime, timedelta

from almanac.services import sync_series_rsvps
from groups.models.group import Group

from ..models import (
    Event, EventOccurrence, Decorator, OccurrenceAttendee,
    EventFollower, ContentStatus
)
from .serializers import (
    EventListSerializer, EventDetailSerializer, EventCreateSerializer,
    EventOccurrenceSerializer, OccurrenceAttendeeSerializer,
    EventRSVPSerializer, EventFollowerSerializer, DecoratorSerializer
)


# =============================================================================
# MIXINS - Shared logic across contexts
# =============================================================================

class EventListCreateMixin:
    """
    Shared logic for listing and creating events across contexts.
    Subclasses implement get_sponsor() to provide context.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventDetailSerializer
    pagination_class = None  # Override in subclass if needed

    def get_sponsor(self):
        """
        Return the sponsor object (Group, User, etc).
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement get_sponsor()")

    def get_queryset(self):
        """Get events for this sponsor, with permission checks"""
        sponsor = self.get_sponsor()
        sponsor_ct = ContentType.objects.get_for_model(sponsor.__class__)

        return Event.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor.id
        ).select_related('series').prefetch_related(
            'decorator_assignments__decorator',
            'gathering_extension'
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list' or self.request.method == 'GET':
            return EventListSerializer
        elif self.request.method == 'POST':
            return EventCreateSerializer
        return EventDetailSerializer

    @transaction.atomic
    def perform_create(self, serializer):
        """Create event with sponsor context"""
        print(f"DEBUG: perform_create() called")
        sponsor = self.get_sponsor()
        print(f"DEBUG: perform_create sponsor = {sponsor}")
        author = self.request.user
        data = serializer.validated_data
        event_type = data['event_type']

        try:
            if event_type == 'single':
                event = Event.objects.create_single_event(
                    title=data['title'],
                    start_time=data['start_time'],
                    end_time=data['end_time'],
                    sponsor=sponsor,
                    author=author,
                    location=data.get('location', ''),
                    description=data.get('description', ''),
                    event_format=data.get('event_format', 'workshop'),
                    max_attendees=data.get('max_attendees'),
                    registration_required=data.get('registration_required', False),
                    registration_deadline_hours=data.get('registration_deadline_hours', 24),
                    decorators=data.get('decorators', [])
                )

            elif event_type == 'adhoc_series':
                adhoc_slots = []
                for slot in data['adhoc_slots']:
                    start = slot['start']
                    end = slot['end']

                    if isinstance(start, str):
                        start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    if isinstance(end, str):
                        end = datetime.fromisoformat(end.replace('Z', '+00:00'))

                    adhoc_slots.append({
                        'start': start,
                        'end': end,
                        'title_override': slot.get('title_override', ''),
                        'location_override': slot.get('location_override', '')
                    })

                event = Event.objects.create_adhoc_series(
                    title=data['title'],
                    sponsor=sponsor,
                    author=author,
                    adhoc_slots=adhoc_slots,
                    location=data.get('location', ''),
                    description=data.get('description', ''),
                    event_format=data.get('event_format', 'workshop'),
                    max_attendees=data.get('max_attendees'),
                    registration_required=data.get('registration_required', False),
                    registration_deadline_hours=data.get('registration_deadline_hours', 24),
                    decorators=data.get('decorators', [])
                )

            elif event_type == 'gathering':
                gathering_data = data.get('gathering_data', {})

                event = Event.objects.create_gathering(
                    title=data['title'],
                    start_time=data['start_time'],
                    end_time=data['end_time'],
                    sponsor=sponsor,
                    author=author,
                    gathering_data=gathering_data,
                    location=data.get('location', ''),
                    description=data.get('description', ''),
                    max_attendees=data.get('max_attendees'),
                    registration_required=data.get('registration_required', False),
                    registration_deadline_hours=data.get('registration_deadline_hours', 24),
                    decorators=data.get('decorators', [])
                )

            else:
                raise ValueError(f'Unknown event_type: {event_type}')

            # Events created in DRAFT status
            serializer.instance = event

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise


class EventDetailMixin:
    """Shared logic for event detail/action views"""
    permission_classes = [permissions.IsAuthenticated]

    def get_event_from_kwargs(self):
        """Extract event_id from URL kwargs and fetch event"""
        event_id = self.kwargs.get('event_id')
        event = get_object_or_404(Event, id=event_id)
        return event

    def check_event_permissions(self, event, user, require_author=False):
        """
        Check if user can modify this event.
        If require_author=True, only author can modify.
        Otherwise, author or organizer followers can modify.
        """
        if require_author:
            if event.author != user:
                raise PermissionDenied("Only event author can perform this action")
        else:
            if event.author != user and not event.followers.filter(
                user=user, follow_type='organizer'
            ).exists():
                raise PermissionDenied("Permission denied")


# =============================================================================
# SITE-WIDE EVENT VIEWS
# =============================================================================

class EventListCreateView(generics.ListCreateAPIView):
    """
    List and create site-wide events (no specific sponsor).
    GET /api/almanac/events
    POST /api/almanac/events
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventDetailSerializer
    pagination_class = None

    def get_queryset(self):
        """Show published events or user's own events"""
        queryset = Event.objects.select_related('series').prefetch_related(
            'decorator_assignments__decorator',
            'gathering_extension'
        )

        queryset = queryset.filter(
            models.Q(status=ContentStatus.PUBLISHED) |
            models.Q(author=self.request.user) |
            models.Q(followers__user=self.request.user, followers__follow_type='organizer')
        ).distinct()

        # Apply filters
        decorator = self.request.query_params.get('decorator')
        if decorator:
            queryset = queryset.filter(
                decorator_assignments__decorator__slug=decorator,
                decorator_assignments__decorator__is_active=True
            ).distinct()

        kind = self.request.query_params.get('kind')
        if kind == 'event':
            queryset = queryset.filter(gathering_extension__isnull=True)
        elif kind == 'gathering':
            queryset = queryset.filter(gathering_extension__isnull=False)

        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return EventListSerializer
        return EventCreateSerializer


class EventDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Get, update, or delete an event.
    GET    /api/almanac/events/{id}
    PUT    /api/almanac/events/{id}
    DELETE /api/almanac/events/{id}
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventDetailSerializer
    lookup_url_kwarg = 'event_id'
    lookup_field = 'id'

    def get_queryset(self):
        return Event.objects.select_related('series').prefetch_related(
            'decorator_assignments__decorator',
            'gathering_extension'
        )


class EventPublishView(generics.CreateAPIView):
    """Publish a draft event"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventDetailSerializer

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        # Check permissions
        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        if event.status != ContentStatus.DRAFT:
            return Response(
                {'error': 'Only draft events can be published'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event.status = ContentStatus.PUBLISHED
        event.published_at = timezone.now()
        event.save()

        return Response(EventDetailSerializer(event).data)


class EventUnpublishView(generics.CreateAPIView):
    """Unpublish an event (move to draft)"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventDetailSerializer

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        event.status = ContentStatus.DRAFT
        event.save()

        return Response(EventDetailSerializer(event).data)


class EventRSVPView(generics.CreateAPIView):
    """RSVP to entire event series"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventRSVPSerializer

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])
        serializer = self.get_serializer(
            data=request.data,
            context={'event': event, 'user': request.user}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)


class EventFollowView(generics.CreateAPIView):
    """Follow or unfollow an event"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        follower, created = EventFollower.objects.get_or_create(
            event=event,
            user=request.user,
            defaults={
                'follow_type': request.data.get('follow_type', 'following'),
                'notify_new_occurrences': request.data.get('notify_new_occurrences', True),
                'notify_changes': request.data.get('notify_changes', True)
            }
        )

        serializer = EventFollowerSerializer(follower)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=response_status)

    def delete(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        try:
            follower = EventFollower.objects.get(event=event, user=request.user)
            follower.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except EventFollower.DoesNotExist:
            return Response(
                {'error': 'Not following this event'},
                status=status.HTTP_404_NOT_FOUND
            )


class EventAttendeesView(generics.ListAPIView):
    """Get all attendees for an event"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OccurrenceAttendeeSerializer

    def get_queryset(self):
        event = get_object_or_404(Event, id=self.kwargs['event_id'])
        return OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            status__in=['going', 'maybe', 'attended']
        ).select_related('user', 'occurrence').order_by('created_at')


class EventSyncRsvpsView(generics.CreateAPIView):
    """Sync RSVPs after occurrence changes"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        # Check permissions
        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        try:
            sync_series_rsvps(event)
            return Response({'status': 'RSVPs synced successfully'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'Sync failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class EventAnalyticsView(generics.RetrieveAPIView):
    """Get analytics for an event"""
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        # Check permissions
        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        # Calculate analytics
        total_occurrences = event.series.occurrences.all().count() if event.series else 0
        past_occurrences = event.series.occurrences.filter(end__lt=timezone.now()).count() if event.series else 0

        total_rsvps = OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            status__in=['going', 'maybe']
        ).count() if event.series else 0

        total_attended = OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            status='attended'
        ).count() if event.series else 0

        followers_count = event.followers.count()

        occurrence_stats = []
        if event.series:
            # Use aggregation to avoid N+1 queries
            from django.db.models import Count, Q

            occurrences_with_counts = event.series.occurrences.all().order_by('start').annotate(
                going_count=Count('attendees', filter=Q(attendees__status='going')),
                maybe_count=Count('attendees', filter=Q(attendees__status='maybe')),
                attended_count=Count('attendees', filter=Q(attendees__status='attended'))
            )

            for occurrence in occurrences_with_counts:
                occurrence_stats.append({
                    'occurrence_id': str(occurrence.id),
                    'start': occurrence.start.isoformat(),
                    'title': occurrence.effective_title,
                    'going': occurrence.going_count,
                    'maybe': occurrence.maybe_count,
                    'attended': occurrence.attended_count,
                    'is_past': occurrence.is_past
                })

        return Response({
            'event_id': str(event.id),
            'title': event.title,
            'status': event.status,
            'published_at': event.published_at,
            'total_occurrences': total_occurrences,
            'past_occurrences': past_occurrences,
            'total_rsvps': total_rsvps,
            'total_attended': total_attended,
            'followers_count': followers_count,
            'attendance_rate': (total_attended / total_rsvps * 100) if total_rsvps > 0 else 0,
            'occurrence_stats': occurrence_stats
        })


# =============================================================================
# GROUP-SCOPED EVENT VIEWS
# =============================================================================

class GroupEventListCreateView(EventListCreateMixin, generics.ListCreateAPIView):
    """
    List and create events for a specific group.
    GET  /api/groups/:slug/events
    POST /api/groups/:slug/events
    """

    def get_sponsor(self):
        print(f"DEBUG: get_sponsor() called")
        print(f"DEBUG: self.kwargs = {self.kwargs}")
        slug = self.kwargs.get('slug')
        print(f"DEBUG: slug = {slug}")
        if not slug:
            raise ValidationError("Group slug not found in URL")
        group = get_object_or_404(Group, slug=slug)
        print(f"DEBUG: group = {group}")
        return group

    def list(self, request, *args, **kwargs):
        """Override to show draft events if user is author/organizer"""
        self.action = 'list'
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Create event and return detailed response"""
        self.action = 'create'
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # Return using EventDetailSerializer for the response
        from .serializers import EventDetailSerializer
        response_serializer = EventDetailSerializer(serializer.instance)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED
        )


class GroupEventDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Get, update, or delete a group event.
    GET    /api/groups/:slug/events/{id}
    PUT    /api/groups/:slug/events/{id}
    DELETE /api/groups/:slug/events/{id}
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventDetailSerializer
    lookup_url_kwarg = 'event_id'
    lookup_field = 'id'

    def get_queryset(self):
        group = get_object_or_404(Group, slug=self.kwargs['slug'])
        sponsor_ct = ContentType.objects.get_for_model(Group)

        return Event.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=group.id
        ).select_related('series').prefetch_related(
            'decorator_assignments__decorator',
            'gathering_extension'
        )


class GroupEventPublishView(generics.CreateAPIView):
    """Publish a draft group event"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        if event.status != ContentStatus.DRAFT:
            return Response(
                {'error': 'Only draft events can be published'},
                status=status.HTTP_400_BAD_REQUEST
            )

        event.status = ContentStatus.PUBLISHED
        event.published_at = timezone.now()
        event.save()

        return Response(EventDetailSerializer(event).data)


class GroupEventUnpublishView(generics.CreateAPIView):
    """Unpublish a group event"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        event.status = ContentStatus.DRAFT
        event.save()

        return Response(EventDetailSerializer(event).data)


class GroupEventRSVPView(generics.CreateAPIView):
    """RSVP to a group event series"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventRSVPSerializer

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])
        serializer = self.get_serializer(
            data=request.data,
            context={'event': event, 'user': request.user}
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)


class GroupEventFollowView(generics.CreateAPIView):
    """Follow or unfollow a group event"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        follower, created = EventFollower.objects.get_or_create(
            event=event,
            user=request.user,
            defaults={
                'follow_type': request.data.get('follow_type', 'following'),
                'notify_new_occurrences': request.data.get('notify_new_occurrences', True),
                'notify_changes': request.data.get('notify_changes', True)
            }
        )

        serializer = EventFollowerSerializer(follower)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(serializer.data, status=response_status)

    def delete(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        try:
            follower = EventFollower.objects.get(event=event, user=request.user)
            follower.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except EventFollower.DoesNotExist:
            return Response(
                {'error': 'Not following this event'},
                status=status.HTTP_404_NOT_FOUND
            )


class GroupEventAttendeesView(generics.ListAPIView):
    """Get all attendees for a group event"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OccurrenceAttendeeSerializer

    def get_queryset(self):
        event = get_object_or_404(Event, id=self.kwargs['event_id'])
        return OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            status__in=['going', 'maybe', 'attended']
        ).select_related('user', 'occurrence').order_by('created_at')


class GroupEventSyncRsvpsView(generics.CreateAPIView):
    """Sync RSVPs for a group event"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        try:
            sync_series_rsvps(event)
            return Response({'status': 'RSVPs synced successfully'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {'error': f'Sync failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class GroupEventAnalyticsView(generics.RetrieveAPIView):
    """Get analytics for a group event"""
    permission_classes = [permissions.IsAuthenticated]

    def retrieve(self, request, *args, **kwargs):
        event = get_object_or_404(Event, id=kwargs['event_id'])

        if event.author != request.user and not event.followers.filter(
            user=request.user, follow_type='organizer'
        ).exists():
            raise PermissionDenied("Permission denied")

        # Same analytics logic as site-wide
        total_occurrences = event.series.occurrences.all().count() if event.series else 0
        past_occurrences = event.series.occurrences.filter(end__lt=timezone.now()).count() if event.series else 0

        total_rsvps = OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            status__in=['going', 'maybe']
        ).count() if event.series else 0

        total_attended = OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            status='attended'
        ).count() if event.series else 0

        followers_count = event.followers.count()

        occurrence_stats = []
        if event.series:
            # Use aggregation to avoid N+1 queries
            from django.db.models import Count, Q

            occurrences_with_counts = event.series.occurrences.all().order_by('start').annotate(
                going_count=Count('attendees', filter=Q(attendees__status='going')),
                maybe_count=Count('attendees', filter=Q(attendees__status='maybe')),
                attended_count=Count('attendees', filter=Q(attendees__status='attended'))
            )

            for occurrence in occurrences_with_counts:
                occurrence_stats.append({
                    'occurrence_id': str(occurrence.id),
                    'start': occurrence.start.isoformat(),
                    'title': occurrence.effective_title,
                    'going': occurrence.going_count,
                    'maybe': occurrence.maybe_count,
                    'attended': occurrence.attended_count,
                    'is_past': occurrence.is_past
                })

        return Response({
            'event_id': str(event.id),
            'title': event.title,
            'status': event.status,
            'published_at': event.published_at,
            'total_occurrences': total_occurrences,
            'past_occurrences': past_occurrences,
            'total_rsvps': total_rsvps,
            'total_attended': total_attended,
            'followers_count': followers_count,
            'attendance_rate': (total_attended / total_rsvps * 100) if total_rsvps > 0 else 0,
            'occurrence_stats': occurrence_stats
        })


# =============================================================================
# OCCURRENCE VIEWS
# =============================================================================

class OccurrenceListView(generics.ListAPIView):
    """List occurrences (published events only)"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventOccurrenceSerializer

    def get_queryset(self):
        return EventOccurrence.objects.select_related(
            'series', 'series__event'
        ).prefetch_related(
            'series__event__decorator_assignments__decorator',
            'attendees'
        ).filter(
            is_cancelled=False,
            series__event__status=ContentStatus.PUBLISHED
        )


class OccurrenceDetailView(generics.RetrieveAPIView):
    """Get occurrence details"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventOccurrenceSerializer
    lookup_url_kwarg = 'occurrence_id'
    lookup_field = 'id'

    def get_queryset(self):
        return EventOccurrence.objects.select_related(
            'series', 'series__event'
        ).prefetch_related(
            'series__event__decorator_assignments__decorator',
            'attendees'
        ).filter(
            is_cancelled=False,
            series__event__status=ContentStatus.PUBLISHED
        )


class OccurrenceRSVPView(generics.CreateAPIView):
    """RSVP to a specific occurrence"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        occurrence = get_object_or_404(EventOccurrence, id=kwargs['occurrence_id'])

        status_choice = request.data.get('status', 'going')
        notes = request.data.get('registration_notes', '')

        attendee, created = OccurrenceAttendee.objects.get_or_create(
            occurrence=occurrence,
            user=request.user,
            defaults={
                'status': status_choice,
                'registration_notes': notes
            }
        )

        if not created:
            attendee.status = status_choice
            attendee.registration_notes = notes
            attendee.save()

        serializer = OccurrenceAttendeeSerializer(attendee)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class OccurrenceCancelRSVPView(generics.CreateAPIView):
    """Cancel RSVP to a specific occurrence"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        occurrence = get_object_or_404(EventOccurrence, id=kwargs['occurrence_id'])

        try:
            attendee = OccurrenceAttendee.objects.get(
                occurrence=occurrence,
                user=request.user
            )
            attendee.status = 'not_going'
            attendee.save()

            return Response({'status': 'RSVP cancelled'}, status=status.HTTP_200_OK)

        except OccurrenceAttendee.DoesNotExist:
            return Response(
                {'error': 'No RSVP found'},
                status=status.HTTP_404_NOT_FOUND
            )


# =============================================================================
# CALENDAR VIEWS
# =============================================================================

class CalendarOccurrencesView(generics.ListAPIView):
    """Get calendar occurrences for display (published events only)"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventOccurrenceSerializer

    def get_queryset(self):
        try:
            start_str = self.request.GET.get('start')
            end_str = self.request.GET.get('end')

            if not start_str or not end_str:
                return EventOccurrence.objects.none()

            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))

            occurrences = EventOccurrence.objects.for_calendar_view(start_date, end_date)
            occurrences = occurrences.filter(series__event__status=ContentStatus.PUBLISHED)

            decorator_filter = self.request.GET.get('decorator')
            if decorator_filter:
                occurrences = occurrences.filter(
                    series__event__decorator_assignments__decorator__slug=decorator_filter,
                    series__event__decorator_assignments__decorator__is_active=True
                ).distinct()

            kind_filter = self.request.GET.get('kind')
            if kind_filter == 'event':
                occurrences = occurrences.filter(series__event__gathering_extension__isnull=True)
            elif kind_filter == 'gathering':
                occurrences = occurrences.filter(series__event__gathering_extension__isnull=False)

            return occurrences

        except ValueError:
            return EventOccurrence.objects.none()




class GroupCalendarOccurrencesView(generics.ListAPIView):
    """Get calendar occurrences for a specific group (published events only)"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventOccurrenceSerializer

    def get_queryset(self):
        try:
            group_slug = self.kwargs.get('slug')
            group = get_object_or_404(Group, slug=group_slug)

            start_str = self.request.GET.get('start')
            end_str = self.request.GET.get('end')

            if not start_str or not end_str:
                return EventOccurrence.objects.none()

            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))

            # Get sponsor content type for Group
            sponsor_ct = ContentType.objects.get_for_model(Group)

            # Filter: group + published + in date range
            occurrences = EventOccurrence.objects.filter(
                series__event__status=ContentStatus.PUBLISHED,
                series__event__sponsor_content_type=sponsor_ct,
                series__event__sponsor_object_id=group.id,
                start__gte=start_date,
                end__lte=end_date,
                is_cancelled=False
            ).select_related(
                'series', 'series__event'
            ).prefetch_related(
                'series__event__decorator_assignments__decorator',
                'series__event__gathering_extension',
                'attendees'
            ).order_by('start')

            # Apply optional filters
            decorator_filter = self.request.GET.get('decorator')
            if decorator_filter:
                occurrences = occurrences.filter(
                    series__event__decorator_assignments__decorator__slug=decorator_filter,
                    series__event__decorator_assignments__decorator__is_active=True
                ).distinct()

            kind_filter = self.request.GET.get('kind')
            if kind_filter == 'event':
                occurrences = occurrences.filter(series__event__gathering_extension__isnull=True)
            elif kind_filter == 'gathering':
                occurrences = occurrences.filter(series__event__gathering_extension__isnull=False)

            return occurrences

        except ValueError:
            return EventOccurrence.objects.none()



# =========================================================================
# ATTENDEES VIEWS
# =========================================================================





class GroupEventAttendeesView(generics.ListAPIView):
    """
    List all attendees for a group event.
    Shows who RSVP'd with their status and notes.

    GET /api/groups/:slug/events/:event_id/attendees
    """
    serializer_class = OccurrenceAttendeeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        event_id = self.kwargs.get('event_id')
        group_slug = self.kwargs.get('slug')

        # Get the event
        event = get_object_or_404(Event, id=event_id)

        # Verify the sponsor (Group) matches the requested slug
        if not event.sponsor or event.sponsor.slug != group_slug:
            return OccurrenceAttendee.objects.none()

        # Get attendees from the next/current occurrence
        occurrence = event.next_occurrence
        if not occurrence:
            return OccurrenceAttendee.objects.none()

        return OccurrenceAttendee.objects.filter(
            occurrence=occurrence,
            status__in=['going', 'maybe', 'not_going']
        ).select_related('user', 'occurrence')


class GroupEventRSVPBreakdownView(generics.GenericAPIView):
    """
    Get RSVP breakdown for a group event.
    Returns count of Going/Maybe/Not Going.

    GET /api/groups/:slug/events/:event_id/rsvp-breakdown
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        event_id = self.kwargs.get('event_id')
        group_slug = self.kwargs.get('slug')

        # Get the event
        event = get_object_or_404(Event, id=event_id)

        # Verify the sponsor (Group) matches the requested slug
        if not event.sponsor or event.sponsor.slug != group_slug:
            return Response({'detail': 'Not found.'}, status=404)

        # Get breakdown from the next/current occurrence
        occurrence = event.next_occurrence
        if not occurrence:
            return Response({
                'going': 0,
                'maybe': 0,
                'not_going': 0,
            })

        breakdown = {
            'going': occurrence.attendees.filter(status='going').count(),
            'maybe': occurrence.attendees.filter(status='maybe').count(),
            'not_going': occurrence.attendees.filter(status='not_going').count(),
        }

        return Response(breakdown)



# Site-wide versions (optional, for consistency)
class EventAttendeesView(generics.ListAPIView):
    """List all attendees for an event"""
    serializer_class = OccurrenceAttendeeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        event_id = self.kwargs.get('event_id')
        event = get_object_or_404(Event, id=event_id)

        occurrence = event.next_occurrence
        if not occurrence:
            return OccurrenceAttendee.objects.none()

        return OccurrenceAttendee.objects.filter(
            occurrence=occurrence,
            status__in=['going', 'maybe', 'not_going']
        ).select_related('user', 'occurrence')


class EventRSVPBreakdownView(generics.GenericAPIView):
    """Get RSVP breakdown for an event"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        event_id = self.kwargs.get('event_id')
        event = get_object_or_404(Event, id=event_id)

        occurrence = event.next_occurrence
        if not occurrence:
            return Response({
                'going': 0,
                'maybe': 0,
                'not_going': 0,
            })

        breakdown = {
            'going': occurrence.attendees.filter(status='going').count(),
            'maybe': occurrence.attendees.filter(status='maybe').count(),
            'not_going': occurrence.attendees.filter(status='not_going').count(),
        }

        return Response(breakdown)








class MyCalendarOccurrencesView(generics.ListAPIView):
    """Get calendar occurrences for events user is attending/following"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EventOccurrenceSerializer

    def get_queryset(self):
        try:
            start_str = self.request.GET.get('start')
            end_str = self.request.GET.get('end')

            if not start_str or not end_str:
                return EventOccurrence.objects.none()

            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00'))

            user_occurrences = EventOccurrence.objects.for_calendar_view(start_date, end_date).filter(
                series__event__status=ContentStatus.PUBLISHED
            ).filter(
                models.Q(attendees__user=self.request.user, attendees__status__in=['going', 'maybe']) |
                models.Q(series__event__followers__user=self.request.user)
            ).distinct()

            return user_occurrences

        except ValueError:
            return EventOccurrence.objects.none()


# =============================================================================
# UTILITY VIEWS
# =============================================================================

class DecoratorListView(generics.ListAPIView):
    """Get all available decorators"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DecoratorSerializer
    queryset = Decorator.objects.filter(is_active=True).order_by('sort_order', 'name')


class MyEventsSummaryView(generics.GenericAPIView):
    """Get summary of user's event activity"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        attending_count = OccurrenceAttendee.objects.filter(
            user=user,
            status='going',
            occurrence__start__gte=timezone.now(),
            occurrence__series__event__status=ContentStatus.PUBLISHED
        ).count()

        following_count = EventFollower.objects.filter(user=user).count()

        authored_count = Event.objects.filter(author=user, status=ContentStatus.PUBLISHED).count()

        upcoming_occurrences = EventOccurrence.objects.filter(
            attendees__user=user,
            attendees__status='going',
            start__gte=timezone.now(),
            is_cancelled=False,
            series__event__status=ContentStatus.PUBLISHED
        ).select_related('series', 'series__event').order_by('start')[:5]

        upcoming_serializer = EventOccurrenceSerializer(upcoming_occurrences, many=True)

        return Response({
            'attending_count': attending_count,
            'following_count': following_count,
            'authored_count': authored_count,
            'upcoming_events': upcoming_serializer.data
        })


class BulkRSVPView(generics.CreateAPIView):
    """RSVP to multiple occurrences at once"""
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        occurrence_ids = request.data.get('occurrence_ids', [])
        status_choice = request.data.get('status', 'going')
        notes = request.data.get('registration_notes', '')

        if not occurrence_ids:
            return Response(
                {'error': 'occurrence_ids required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                results = []

                for occurrence_id in occurrence_ids:
                    try:
                        occurrence = EventOccurrence.objects.get(
                            id=occurrence_id,
                            series__event__status=ContentStatus.PUBLISHED
                        )
                    except EventOccurrence.DoesNotExist:
                        results.append({
                            'occurrence_id': occurrence_id,
                            'status': 'error',
                            'message': 'Occurrence not found or event not published'
                        })
                        continue

                    if occurrence.is_full() and status_choice == 'going':
                        results.append({
                            'occurrence_id': occurrence_id,
                            'status': 'error',
                            'message': 'Event is full'
                        })
                        continue

                    attendee, created = OccurrenceAttendee.objects.get_or_create(
                        occurrence=occurrence,
                        user=request.user,
                        defaults={
                            'status': status_choice,
                            'registration_notes': notes
                        }
                    )

                    if not created:
                        attendee.status = status_choice
                        attendee.registration_notes = notes
                        attendee.save()

                    results.append({
                        'occurrence_id': occurrence_id,
                        'status': 'success',
                        'created': created
                    })

                return Response({'results': results}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {'error': f'Bulk RSVP failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )