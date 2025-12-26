# almanac/api/serializers.py

"""
Mixtape Almanac API Serializers
Clean, efficient serializers for Event management
Updated for Event publishing workflow and new model structure
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils import timezone
from ..models import (
    Event, EventSeries, EventOccurrence, GatheringExtension,
    EventDecorator, Decorator, OccurrenceAttendee, EventFollower, ContentStatus
)


# =============================================================================
# CORE SERIALIZERS
# =============================================================================

class DecoratorSerializer(serializers.ModelSerializer):
    """Serializer for decorator definitions"""

    class Meta:
        model = Decorator
        fields = ['slug', 'name', 'icon', 'description', 'has_context_data', 'is_active']


class EventDecoratorSerializer(serializers.ModelSerializer):
    """Serializer for event decorator assignments with context"""

    decorator = DecoratorSerializer(read_only=True)
    decorator_slug = serializers.CharField(write_only=True, source='decorator.slug')

    class Meta:
        model = EventDecorator
        fields = ['id', 'decorator', 'decorator_slug', 'context_data', 'assigned_at']
        read_only_fields = ['id', 'assigned_at']


class GatheringExtensionSerializer(serializers.ModelSerializer):
    """Serializer for gathering-specific fields"""

    class Meta:
        model = GatheringExtension
        fields = [
            'id', 'accommodation_available', 'meals_included', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EventSeriesSerializer(serializers.ModelSerializer):
    """Serializer for EventSeries scheduling metadata"""

    next_occurrence = serializers.SerializerMethodField()
    sponsor_display = serializers.ReadOnlyField()

    class Meta:
        model = EventSeries
        fields = [
            'id', 'title', 'slug', 'summary',
            'timezone', 'default_duration_minutes',
            'rrule',
            'is_active', 'is_recurring',
            'next_occurrence', 'sponsor_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_next_occurrence(self, obj):
        """Get next upcoming occurrence"""
        next_occ = obj.next_occurrence
        if next_occ:
            return EventOccurrenceSerializer(next_occ).data
        return None


class EventOccurrenceSerializer(serializers.ModelSerializer):
    """Serializer for individual event occurrences"""

    effective_title = serializers.ReadOnlyField()
    effective_location = serializers.ReadOnlyField()
    duration_hours = serializers.ReadOnlyField()
    is_past = serializers.ReadOnlyField()
    is_happening_now = serializers.ReadOnlyField()
    attendee_count = serializers.ReadOnlyField(source='get_attendee_count')
    is_full = serializers.ReadOnlyField()

    class Meta:
        model = EventOccurrence
        fields = [
            'id', 'start', 'end', 'effective_title', 'effective_location',
            'title_override', 'location_override', 'is_cancelled', 'cancellation_reason',
            'duration_hours', 'is_past', 'is_happening_now', 'attendee_count', 'is_full',
            'notes', 'actual_attendance', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class CalendarOccurrenceSerializer(serializers.ModelSerializer):
    """
    Serializer for calendar view occurrences.
    Includes event metadata needed for calendar display.
    """
    # IDs for navigation
    series_id = serializers.CharField(source='series.id', read_only=True)
    event_id = serializers.CharField(source='series.event.id', read_only=True)
    event_slug = serializers.CharField(source='series.event.slug', read_only=True)

    # Display fields
    title = serializers.CharField(source='effective_title', read_only=True)
    location = serializers.CharField(source='effective_location', read_only=True)

    # Event metadata
    kind = serializers.SerializerMethodField()
    event_format = serializers.CharField(source='series.event.event_format', read_only=True)
    event_status = serializers.CharField(source='series.event.status', read_only=True)
    sponsor_display = serializers.CharField(source='series.event.sponsor_display', read_only=True)

    # Capacity info
    capacity = serializers.IntegerField(source='series.event.max_attendees', read_only=True)
    attendee_count = serializers.ReadOnlyField(source='get_attendee_count')
    is_full = serializers.ReadOnlyField()

    # Decorators
    decorators = serializers.SerializerMethodField()

    # Gathering info
    accommodation_available = serializers.SerializerMethodField()
    meals_included = serializers.SerializerMethodField()

    class Meta:
        model = EventOccurrence
        fields = [
            'id', 'series_id', 'event_id', 'event_slug',
            'title', 'kind', 'start', 'end', 'location',
            'decorators', 'event_format', 'event_status',
            'capacity', 'attendee_count', 'is_full',
            'sponsor_display', 'accommodation_available', 'meals_included',
            'is_cancelled'
        ]
        read_only_fields = ['id']

    def get_kind(self, obj):
        """Determine if this is an event or gathering"""
        try:
            has_gathering = hasattr(obj.series.event, 'gathering_extension') and obj.series.event.gathering_extension is not None
            return 'gathering' if has_gathering else 'event'
        except:
            return 'event'

    def get_decorators(self, obj):
        """Get decorator info for the event"""
        try:
            return [
                {
                    'slug': da.decorator.slug,
                    'icon': da.decorator.icon,
                    'name': da.decorator.name,
                    'context_data': da.context_data or {}
                }
                for da in obj.series.event.decorator_assignments.filter(decorator__is_active=True)
            ]
        except:
            return []

    def get_accommodation_available(self, obj):
        """Check if accommodation is available"""
        try:
            if hasattr(obj.series.event, 'gathering_extension') and obj.series.event.gathering_extension:
                return obj.series.event.gathering_extension.accommodation_available
        except:
            pass
        return False

    def get_meals_included(self, obj):
        """Check if meals are included"""
        try:
            if hasattr(obj.series.event, 'gathering_extension') and obj.series.event.gathering_extension:
                return obj.series.event.gathering_extension.meals_included
        except:
            pass
        return False


class EventListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for event lists"""

    sponsor_display = serializers.ReadOnlyField()
    decorators = EventDecoratorSerializer(source='decorator_assignments', many=True, read_only=True)
    next_occurrence = serializers.SerializerMethodField()
    is_recurring = serializers.ReadOnlyField()
    status = serializers.CharField()
    published_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Event
        fields = [
            'id', 'slug', 'title', 'location', 'sponsor_display', 'author',
            'status', 'published_at',
            'event_format', 'max_attendees',
            'next_occurrence', 'is_recurring',
            'decorators', 'created_at'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'author']

    def get_next_occurrence(self, obj):
        """Get next upcoming occurrence"""
        next_occ = obj.next_occurrence
        if next_occ:
            return EventOccurrenceSerializer(next_occ).data
        return None


class EventDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for full event information"""

    # Read-only computed fields
    sponsor_display = serializers.ReadOnlyField()
    is_recurring = serializers.ReadOnlyField()
    registration_deadline = serializers.SerializerMethodField()
    total_attendees = serializers.SerializerMethodField()

    # Related data
    series = EventSeriesSerializer(read_only=True)
    decorators = EventDecoratorSerializer(source='decorator_assignments', many=True, read_only=True)
    gathering_extension = GatheringExtensionSerializer(read_only=True)
    upcoming_occurrences = serializers.SerializerMethodField()

    # Publishing workflow
    status = serializers.CharField()
    published_at = serializers.DateTimeField(read_only=True)

    # Write-only fields for creation
    decorator_assignments_data = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text="List of decorator assignments: [{'slug': 'is_potluck', 'context_data': {...}}]"
    )
    gathering_data = GatheringExtensionSerializer(write_only=True, required=False)

    class Meta:
        model = Event
        fields = [
            'id', 'slug', 'title', 'description', 'location', 'sponsor_display', 'author',
            'status', 'published_at',
            'event_format', 'max_attendees', 'registration_required', 'registration_deadline_hours',
            'visible_to_parent',
            'is_recurring', 'registration_deadline', 'total_attendees',
            'series', 'decorators', 'gathering_extension', 'upcoming_occurrences',
            'decorator_assignments_data', 'gathering_data', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at', 'author', 'published_at']

    def get_registration_deadline(self, obj):
        """Calculate registration deadline from first occurrence"""
        if obj.next_occurrence:
            return (obj.next_occurrence.start - timezone.timedelta(hours=obj.registration_deadline_hours)).isoformat()
        return None

    def get_total_attendees(self, obj):
        """Get total attendees across all occurrences"""
        return OccurrenceAttendee.objects.filter(
            occurrence__series=obj.series,
            status__in=['going', 'attended']
        ).count() if obj.series else 0

    def get_upcoming_occurrences(self, obj):
        """Get upcoming occurrences with limit"""
        occs = obj.upcoming_occurrences[:5]  # Show next 5
        return EventOccurrenceSerializer(occs, many=True).data









class EventCreateSerializer(serializers.Serializer):

    """Serializer for creating events with different patterns"""

    # Core event fields
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, required=False)
    location = serializers.CharField(max_length=300, allow_blank=True, required=False)
    event_format = serializers.ChoiceField(choices=Event._meta.get_field('event_format').choices, required=False)

    # Capacity and registration
    max_attendees = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    registration_required = serializers.BooleanField(default=False)
    registration_deadline_hours = serializers.IntegerField(default=24, min_value=1)

    # Event type and timing (WRITE ONLY - not on model)
    EVENT_TYPES = [
        ('single', 'Single Event'),
        ('adhoc_series', 'Custom Date Series'),
        ('gathering', 'Gathering/Retreat'),
        ('recurring', 'Recurring Event'),
    ]
    event_type = serializers.ChoiceField(choices=EVENT_TYPES, write_only=True)

    # Single event timing (WRITE ONLY)
    start_time = serializers.DateTimeField(required=False, write_only=True)
    end_time = serializers.DateTimeField(required=False, write_only=True)

    # Adhoc series timing (WRITE ONLY)
    adhoc_slots = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
        help_text="List of time slots: [{'start': '2024-10-18T14:00:00Z', 'end': '2024-10-18T17:00:00Z'}]"
    )

    # Recurring event fields (WRITE ONLY)
    rrule = serializers.CharField(required=False, write_only=True, help_text="iCalendar RRULE string")
    timezone = serializers.CharField(required=False, write_only=True, default='UTC')
    default_duration_minutes = serializers.IntegerField(required=False, write_only=True, min_value=1)

    # Decorators (WRITE ONLY)
    decorators = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        write_only=True,
        help_text="List of decorators: [{'slug': 'is_potluck', 'context_data': {'instructions': '...'}}]"
    )

    # Gathering-specific fields (WRITE ONLY)
    gathering_data = GatheringExtensionSerializer(required=False, write_only=True)

    def validate(self, data):
        event_type = data.get('event_type')

        if event_type == 'single':
            if not data.get('start_time') or not data.get('end_time'):
                raise serializers.ValidationError("Single events require start_time and end_time")
            if data.get('start_time') >= data.get('end_time'):
                raise serializers.ValidationError("End time must be after start time")

        elif event_type == 'adhoc_series':
            if not data.get('adhoc_slots'):
                raise serializers.ValidationError("Adhoc series require adhoc_slots")
            for i, slot in enumerate(data.get('adhoc_slots', [])):
                if 'start' not in slot or 'end' not in slot:
                    raise serializers.ValidationError(f"Slot {i} missing start or end time")

        elif event_type == 'gathering':
            if not data.get('start_time') or not data.get('end_time'):
                raise serializers.ValidationError("Gatherings require start_time and end_time")

        elif event_type == 'recurring':
            if not data.get('rrule'):
                raise serializers.ValidationError("Recurring events require rrule")
            if not data.get('start_time') or not data.get('end_time'):
                raise serializers.ValidationError("Recurring events require start_time and end_time for first occurrence")
            if data.get('start_time') >= data.get('end_time'):
                raise serializers.ValidationError("End time must be after start time")
            if not data.get('default_duration_minutes'):
                raise serializers.ValidationError("Recurring events require default_duration_minutes")

        return data





# =============================================================================
# ATTENDANCE SERIALIZERS
# =============================================================================

class OccurrenceAttendeeSerializer(serializers.ModelSerializer):
    """Serializer for RSVP management"""

    # name = serializers.CharField(source='user.get_full_name', read_only=True)
    name = serializers.SerializerMethodField(read_only=True)
    occurrence_title = serializers.CharField(source='occurrence.effective_title', read_only=True)
    notes = serializers.CharField(source='registration_notes', read_only=True)
    rsvp_date = serializers.DateTimeField(source='registered_at', read_only=True)


    class Meta:
        model = OccurrenceAttendee
        fields = [
            'id', 'user', 'name', 'occurrence', 'occurrence_title',
            'status', 'rsvp_date', 'notes', 'checked_in_at',
            'feedback', 'rating'
        ]
        read_only_fields = ['id', 'rsvp_date']


    def get_name(self, obj):
        """
        Return display name with fallback chain:
        1. Full name (if set)
        2. Username (mandatory)
        3. Email (tertiary backup)
        """
        full_name = obj.user.get_full_name()
        if full_name and full_name.strip():
            return full_name
        if obj.user.username:
            return obj.user.username
        return obj.user.email


class EventRSVPSerializer(serializers.Serializer):
    """Serializer for RSVPing to entire event series with optional limit"""

    STATUS_CHOICES = [
        ('going', 'Going'),
        ('maybe', 'Maybe'),
        ('not_going', 'Not Going'),
    ]

    status = serializers.ChoiceField(choices=STATUS_CHOICES, default='going')
    registration_notes = serializers.CharField(allow_blank=True, required=False)
    limit_to = serializers.IntegerField(required=False, allow_null=True, help_text="Limit RSVP to next N occurrences, or None for all")

    def create(self, validated_data):
        event = self.context['event']
        user = self.context['user']
        status = validated_data.get('status', 'going')
        notes = validated_data.get('registration_notes', '')
        limit_to = validated_data.get('limit_to')

        # Use the fan-out RSVP method with limit
        attendees = OccurrenceAttendee.objects.rsvp_to_entire_event(
            event,
            user,
            status=status,
            limit_to=limit_to
        )

        # Add notes to all attendee records
        if notes:
            for attendee in attendees:
                attendee.registration_notes = notes
                attendee.save(update_fields=['registration_notes'])

        return {'attendees_created': len(attendees), 'status': status, 'limit': limit_to}


class EventFollowerSerializer(serializers.ModelSerializer):
    """Serializer for following events"""

    user_display = serializers.CharField(source='user.get_full_name', read_only=True)
    event_title = serializers.CharField(source='event.title', read_only=True)

    class Meta:
        model = EventFollower
        fields = [
            'id', 'user', 'user_display', 'event', 'event_title',
            'follow_type', 'notify_new_occurrences', 'notify_changes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']