# almanac/models.py

"""
Mixtape Almanac - Refined Event Management
Event as base unit, normalized decorators, efficient calendar queries
"""
# models.py - Final Event Models with All Tweaks

from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent, BaseData
from writing.choices import ContentStatus
from writing.models import PublishableContentMixin

User = get_user_model()


# ============================================================================
# EVENT - Ecosystem-facing community activity (BaseContent + Publishable)
# ============================================================================


class EventManager(models.Manager):
    """Manager for Event instances"""

    def get_queryset(self):
        """Exclude soft-deleted events by default"""
        return super().get_queryset().filter(deleted_at__isnull=True)

    def with_deleted(self):
        """Include soft-deleted events"""
        return super().get_queryset()

    def deleted_only(self):
        """Only soft-deleted events"""
        return super().get_queryset().filter(deleted_at__isnull=False)

    def published(self):
        """Filter to published events"""
        return self.filter(status=ContentStatus.PUBLISHED)

    def upcoming(self):
        """Events with upcoming occurrences"""
        return self.filter(
            series__occurrences__start__gte=timezone.now(),
            series__occurrences__is_cancelled=False
        ).distinct()

    def _get_sponsor_fields(self, sponsor):
        """
        Helper to extract sponsor fields for event creation.

        Args:
            sponsor: Group, User, or other sponsor object

        Returns:
            dict: Contains sponsor_content_type and sponsor_object_id
        """
        sponsor_ct = ContentType.objects.get_for_model(sponsor.__class__)
        return {
            'sponsor_content_type': sponsor_ct,
            'sponsor_object_id': str(sponsor.pk)
        }

    def create_single_event(self, title, start_time, end_time, sponsor, author,
                           location='', description='', event_format='workshop',
                           max_attendees=None, registration_required=False,
                           decorators=None, **kwargs):
        """
        Create a single-occurrence event.

        Args:
            title: Event title (public-facing)
            start_time: DateTime for the single occurrence
            end_time: DateTime for the single occurrence
            sponsor: Group/User object (inherits to Event via BaseContent)
            author: User who created it
            location: Event location
            description: Event description
            event_format: Type of event (workshop, lecture, etc.)
            max_attendees: Capacity limit
            registration_required: Whether RSVP is required
            decorators: List of {slug, context_data} dicts
            **kwargs: Additional Event fields

        Returns:
            Event instance
        """
        # Create Event with sponsor (via BaseContent)
        event = self.create(
            title=title,
            location=location,
            description=description,
            event_format=event_format,
            max_attendees=max_attendees,
            registration_required=registration_required,
            author=author,
            **self._get_sponsor_fields(sponsor),
            **kwargs
        )


        # Create EventSeries for scheduling
        duration_minutes = int((end_time - start_time).total_seconds() / 60)
        series = EventSeries.objects.create(
            event=event,
            title=title,
            default_duration_minutes=duration_minutes,
        )

        # Create single EventOccurrence
        EventOccurrence.objects.create(
            series=series,
            recurrence_id=start_time,
            start=start_time,
            end=end_time
        )

        # Add decorators if provided
        if decorators:
            event.add_decorators(decorators)

        return event

    def create_adhoc_series(self, title, sponsor, author, adhoc_slots,
                           location='', description='', event_format='workshop',
                           max_attendees=None, registration_required=False,
                           decorators=None, **kwargs):
        """
        Create event with multiple ad-hoc date slots.

        Args:
            title: Event title
            sponsor: Group/User object
            author: User who created it
            adhoc_slots: List of {start, end, title_override?, location_override?}
            location: Default location
            description: Event description
            event_format: Type of event
            max_attendees: Capacity
            registration_required: RSVP required?
            decorators: List of {slug, context_data}
            **kwargs: Additional Event fields

        Returns:
            Event instance
        """
        # Calculate duration from first slot
        first_slot = adhoc_slots[0]
        duration_minutes = int((first_slot['end'] - first_slot['start']).total_seconds() / 60)

        # Create Event with sponsor
        event = self.create(
            title=title,
            location=location,
            description=description,
            event_format=event_format,
            max_attendees=max_attendees,
            registration_required=registration_required,
            author=author,
            **self._get_sponsor_fields(sponsor),
            **kwargs
        )

        # Create EventSeries
        series = EventSeries.objects.create(
            event=event,
            title=title,
            default_duration_minutes=duration_minutes,
        )

        # Create EventOccurrences from ad-hoc slots
        for slot in adhoc_slots:
            EventOccurrence.objects.create(
                series=series,
                recurrence_id=slot['start'],
                start=slot['start'],
                end=slot['end'],
                title_override=slot.get('title_override', ''),
                location_override=slot.get('location_override', ''),
            )

        # Add decorators
        if decorators:
            event.add_decorators(decorators)

        return event

    def create_gathering(self, title, start_time, end_time, sponsor, author,
                        gathering_data=None, location='', description='',
                        max_attendees=None, registration_required=False,
                        decorators=None, **kwargs):
        """
        Create a gathering event with accommodation/meals info.

        Args:
            title: Event title
            start_time: DateTime for occurrence
            end_time: DateTime for occurrence
            sponsor: Group/User object
            author: User who created it
            gathering_data: {accommodation_available, meals_included}
            location: Event location
            description: Event description
            max_attendees: Capacity
            registration_required: RSVP required?
            decorators: List of {slug, context_data}
            **kwargs: Additional Event fields

        Returns:
            Event instance
        """
        # Create Event with sponsor
        event = self.create(
            title=title,
            location=location,
            description=description,
            event_format='gathering',
            max_attendees=max_attendees,
            registration_required=registration_required,
            author=author,
            **self._get_sponsor_fields(sponsor),
            **kwargs
        )

        # Create EventSeries
        duration_minutes = int((end_time - start_time).total_seconds() / 60)
        series = EventSeries.objects.create(
            event=event,
            title=title,
            default_duration_minutes=duration_minutes,
        )

        # Create EventOccurrence
        EventOccurrence.objects.create(
            series=series,
            recurrence_id=start_time,
            start=start_time,
            end=end_time
        )

        # Create GatheringExtension on event
        if gathering_data:
            GatheringExtension.objects.create(
                event=event,
                accommodation_available=gathering_data.get('accommodation_available', False),
                meals_included=gathering_data.get('meals_included', False),
            )

        # Add decorators
        if decorators:
            event.add_decorators(decorators)

        return event


class Event(PublishableContentMixin, BaseContent):
    """
    Ecosystem-facing community activity.
    Everything is an event - some just have extra logistics.

    Inherits from PublishableContentMixin:
    - status (DRAFT, PUBLISHED, ARCHIVED)
    - published_at

    Inherits from BaseContent:
    - sponsor_content_type, sponsor_object_id, sponsor (GenericFK)
    - created_at, updated_at
    - author

    From BaseData (via BaseContent):
    - summary, title, slug, slug_is_custom, slug_history
    """

    objects = EventManager()

    # Event-specific data
    location = models.CharField(max_length=300, blank=True, default='')
    description = models.TextField(blank=True, default='')
    max_attendees = models.PositiveIntegerField(null=True, blank=True)

    # Event type
    event_format = models.CharField(
        max_length=50,
        choices=[
            ('workshop', 'Workshop'),
            ('lecture', 'Lecture'),
            ('discussion', 'Discussion'),
            ('field_trip', 'Field Trip'),
            ('social', 'Social'),
            ('ceremony', 'Ceremony'),
            ('practice', 'Practice'),
            ('work_party', 'Work Party'),
        ],
        default='workshop'
    )

    # Event state
    registration_required = models.BooleanField(default=False)
    registration_deadline_hours = models.PositiveIntegerField(default=24)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Event"
        verbose_name_plural = "Events"
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['event_format']),
        ]

    def __str__(self):
        return f"{self.title}"

    @property
    def upcoming_occurrences(self):
        """Get upcoming non-cancelled occurrences"""
        if hasattr(self, 'series') and self.series:
            return self.series.occurrences.filter(
                start__gte=timezone.now(),
                is_cancelled=False
            ).order_by('start')
        return EventOccurrence.objects.none()

    @property
    def next_occurrence(self):
        """Get next upcoming occurrence"""
        import logging
        logger = logging.getLogger(__name__)

        has_series = hasattr(self, 'series')
        series_value = self.series if has_series else None
        logger.info(f"[Event.next_occurrence] Event {self.id} ({self.title}): has_series={has_series}, series={series_value}")

        if has_series and self.series:
            next_occ = self.series.next_occurrence
            logger.info(f"[Event.next_occurrence] Series next_occurrence: {next_occ}")
            return next_occ
        return None

    @property
    def is_recurring(self):
        """Check if event has multiple occurrences"""
        if hasattr(self, 'series') and self.series:
            return self.series.is_recurring
        return False

    def add_decorators(self, decorators):
        """
        Add event characteristic decorators with validation.

        Args:
            decorators: List of {slug, context_data} dicts

        Returns:
            tuple: (added_count, invalid_slugs)

        Raises:
            ValueError: If any decorator slugs are invalid
        """
        import logging
        logger = logging.getLogger(__name__)

        added_count = 0
        invalid_slugs = []

        for decorator_data in decorators:
            slug = decorator_data.get('slug')
            if not slug:
                continue

            try:
                decorator = Decorator.objects.get(slug=slug, is_active=True)
                EventDecorator.objects.get_or_create(
                    event=self,
                    decorator=decorator,
                    defaults={'context_data': decorator_data.get('context_data', {})}
                )
                added_count += 1
            except Decorator.DoesNotExist:
                invalid_slugs.append(slug)
                logger.warning(
                    f"Invalid decorator slug '{slug}' for event {self.id} ({self.title})"
                )

        if invalid_slugs:
            raise ValueError(
                f"Invalid decorator slugs: {', '.join(invalid_slugs)}"
            )

        return added_count, invalid_slugs


# ============================================================================
# EVENT SERIES - Scheduling unit (BaseData)
# ============================================================================

class EventSeriesManager(models.Manager):
    """Manager for EventSeries scheduling logic"""

    def active(self):
        return self.filter(is_active=True)

    def upcoming(self):
        """Series with upcoming occurrences"""
        return self.filter(
            occurrences__start__gte=timezone.now(),
            occurrences__is_cancelled=False,
            is_active=True
        ).distinct()


class EventSeries(BaseData):
    """
    Scheduling unit for an event.
    Owns: recurrence logic, timezone, timing
    References: Event (1:1)

    Does NOT need to be publishable - Event.status is the gatekeeper.

    Inherits from BaseData:
    - summary, title, slug, slug_is_custom, slug_history
    - created_at, updated_at

    From BaseModel (via BaseData):
    - id (UUID), get_field_metadata()
    """

    objects = EventSeriesManager()

    # Reference to Event (NO sponsor here - Event owns via BaseContent)
    event = models.OneToOneField(
        Event,
        related_name='series',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    # Scheduling metadata
    timezone = models.CharField(max_length=64, default='UTC')
    default_duration_minutes = models.PositiveIntegerField(default=60)

    # Future recurrence support
    rrule = models.TextField(
        blank=True,
        help_text="RFC 5545 RRULE string for pattern-based recurrence"
    )

    # Series state
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Event Series"
        verbose_name_plural = "Event Series"
        indexes = [
            models.Index(fields=['is_active', 'created_at']),
            models.Index(fields=['event']),
        ]

    def __str__(self):
        return f"{self.title} (Series)"

    @property
    def sponsor(self):
        """Access sponsor from event"""
        return self.event.sponsor if self.event else None

    @property
    def sponsor_display(self):
        """Access sponsor display from event"""
        if self.event:
            return getattr(self.event.sponsor, "display_name", str(self.event.sponsor))
        return None

    @property
    def next_occurrence(self):
        """Get next upcoming occurrence, or first occurrence if none are upcoming"""
        import logging
        logger = logging.getLogger(__name__)

        now = timezone.now()
        all_occurrences = self.occurrences.filter(is_cancelled=False).order_by("start")
        future_occurrences = all_occurrences.filter(start__gte=now)

        logger.info(f"[EventSeries.next_occurrence] Series {self.id}: total_occurrences={all_occurrences.count()}, future_occurrences={future_occurrences.count()}, now={now}")

        # Try to get next future occurrence first
        result = future_occurrences.first()

        # If no future occurrences, fall back to first occurrence (for drafts/past events)
        if not result:
            result = all_occurrences.first()
            if result:
                logger.info(f"[EventSeries.next_occurrence] No future occurrences, returning first: {result.id} at {result.start}")
            else:
                logger.info(f"[EventSeries.next_occurrence] No occurrences found at all")
        else:
            logger.info(f"[EventSeries.next_occurrence] Returning future occurrence: {result.id} at {result.start}")

        return result

    @property
    def is_recurring(self):
        """Check if multiple active occurrences exist"""
        return self.occurrences.filter(is_cancelled=False).count() > 1


# ============================================================================
# EVENT OCCURRENCE - Individual timing instance (BaseModel)
# ============================================================================

class EventOccurrenceManager(models.Manager):
    """Manager for EventOccurrence with calendar queries"""

    def in_date_range(self, start_date, end_date):
        """Get occurrences within date range"""
        return self.filter(
            start__gte=start_date,
            start__lt=end_date,
            is_cancelled=False
        )

    def upcoming(self):
        """Get future occurrences"""
        return self.filter(
            start__gte=timezone.now(),
            is_cancelled=False
        )

    def for_calendar_view(self, start_date, end_date):
        """
        Optimized calendar query.
        Starts from occurrences (canonical timing source).
        """
        return self.select_related(
            "series",
            "series__event"
        ).prefetch_related(
            "series__event__decorator_assignments__decorator",
            "series__event__gathering_extension"
        ).filter(
            is_cancelled=False,
            start__gte=start_date,
            start__lt=end_date
        ).order_by("start")


class EventOccurrence(BaseModel):
    """
    Individual occurrence of an event series.
    Canonical timing source - all calendars reference this.

    Inherits from BaseModel:
    - id (UUID)
    - created_at, updated_at
    - get_field_metadata()
    """

    objects = EventOccurrenceManager()

    # Reference to series
    series = models.ForeignKey(
        EventSeries,
        related_name='occurrences',
        on_delete=models.CASCADE
    )

    # Canonical timing
    recurrence_id = models.DateTimeField(help_text="Canonical instance key")
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField()

    # Occurrence state
    is_cancelled = models.BooleanField(default=False, db_index=True)
    cancellation_reason = models.TextField(blank=True)

    # Per-occurrence overrides
    title_override = models.CharField(max_length=200, blank=True)
    location_override = models.CharField(max_length=300, blank=True)

    # Post-event tracking
    notes = models.TextField(blank=True)
    actual_attendance = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["start"]
        unique_together = [("series", "recurrence_id")]
        indexes = [
            models.Index(fields=["series", "start"]),
            models.Index(fields=["start", "end"]),
            models.Index(fields=["is_cancelled", "start"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(start__lt=models.F("end")),
                name="occ_start_before_end"
            ),
        ]
        verbose_name = "Event Occurrence"
        verbose_name_plural = "Event Occurrences"

    def __str__(self):
        title = self.title_override or self.series.title
        return f"{title} - {self.start.strftime('%Y-%m-%d %H:%M')}"

    @property
    def effective_title(self):
        """Title with override fallback"""
        return self.title_override or self.series.title

    @property
    def effective_location(self):
        """Location with event fallback"""
        if self.location_override:
            return self.location_override
        if self.series.event:
            return self.series.event.location
        return ''

    @property
    def event(self):
        """Get associated Event"""
        return self.series.event if self.series else None

    @property
    def sponsor(self):
        """Get sponsor from event"""
        if self.series and self.series.event:
            return self.series.event.sponsor
        return None

    @property
    def duration(self):
        """Duration as timedelta"""
        return self.end - self.start

    @property
    def duration_hours(self):
        """Duration in hours"""
        return self.duration.total_seconds() / 3600

    @property
    def is_past(self):
        """Whether occurrence has ended"""
        return self.end < timezone.now()

    @property
    def is_happening_now(self):
        """Whether occurrence is currently happening"""
        now = timezone.now()
        return self.start <= now <= self.end

    def get_attendee_count(self):
        """Count of confirmed attendees"""
        return self.attendees.filter(status='going').count()

    def is_full(self):
        """Check if at capacity"""
        if self.series.event and self.series.event.max_attendees:
            return self.get_attendee_count() >= self.series.event.max_attendees
        return False

    def cancel_with_reason(self, reason):
        """Cancel this occurrence with reason"""
        self.is_cancelled = True
        self.cancellation_reason = reason
        self.save()


# ============================================================================
# GATHERING EXTENSION - Extra metadata for gathering events
# ============================================================================

class GatheringExtension(BaseModel):
    """
    Extended info for gathering-type events.

    Inherits from BaseModel:
    - id (UUID)
    - created_at, updated_at
    """

    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name='gathering_extension'
    )

    accommodation_available = models.BooleanField(default=False)
    meals_included = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Gathering Extension"
        verbose_name_plural = "Gathering Extensions"

    def __str__(self):
        return f"Gathering: {self.event.title}"


# ============================================================================
# ATTENDANCE & FOLLOWING
# ============================================================================

class EventFollower(BaseModel):
    """
    Follow entire events for notifications.
    Person who wants updates about an event and all its series.

    Inherits from BaseModel:
    - id (UUID)
    - created_at, updated_at
    """

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='followers'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='followed_events'
    )

    FOLLOW_TYPES = [
        ('following', 'Following'),
        ('interested', 'Interested'),
        ('organizer', 'Organizer'),
    ]
    follow_type = models.CharField(
        max_length=12,
        choices=FOLLOW_TYPES,
        default='following'
    )

    # Notification preferences
    notify_new_occurrences = models.BooleanField(default=True)
    notify_changes = models.BooleanField(default=True)

    class Meta:
        unique_together = ['event', 'user']
        verbose_name = "Event Follower"
        indexes = [
            models.Index(fields=['event', 'user']),
            models.Index(fields=['user', 'follow_type']),
        ]

    def __str__(self):
        return f"{self.user} {self.follow_type} {self.event}"


class OccurrenceAttendeeManager(models.Manager):
    """Manager for occurrence attendance with fan-out RSVP support"""

    def rsvp_to_entire_event(self, event, user, status='going', limit_to=None):
        """
        Fan-out RSVP: Create attendance records for upcoming occurrences.

        Args:
            event: Event instance
            user: User instance
            status: RSVP status ('going', 'maybe', 'not_going')
            limit_to: Integer limiting number of future occurrences, or None for all

        Returns:
            List of OccurrenceAttendee records
        """
        upcoming = event.upcoming_occurrences

        if limit_to:
            upcoming = upcoming[:limit_to]

        attendees = []
        for occurrence in upcoming:
            attendee, created = self.get_or_create(
                occurrence=occurrence,
                user=user,
                defaults={'status': status}
            )
            if not created and attendee.status != status:
                attendee.status = status
                attendee.save()
            attendees.append(attendee)
        return attendees

    def cancel_event_rsvps(self, event, user):
        """Cancel all RSVPs for an event"""
        return self.filter(
            occurrence__series=event.series,
            user=user
        ).update(status='not_going')

    def get_user_attendance_for_event(self, event, user):
        """Get all attendance records for a user across an event series"""
        return self.filter(
            occurrence__series=event.series,
            user=user
        ).select_related('occurrence')


class OccurrenceAttendee(BaseModel):
    """
    Attendance for specific event occurrences.
    Primary RSVP system using fan-out approach.
    Someone who has created relationship/intention to attend a given occurrence.

    Inherits from BaseModel:
    - id (UUID)
    - created_at, updated_at
    - get_field_metadata()
    """

    objects = OccurrenceAttendeeManager()

    occurrence = models.ForeignKey(
        EventOccurrence,
        on_delete=models.CASCADE,
        related_name='attendees'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='occurrence_attendances'
    )

    STATUS_CHOICES = [
        ('going', 'Going'),
        ('maybe', 'Maybe'),
        ('not_going', 'Not Going'),
        ('attended', 'Attended'),
        ('no_show', 'No Show'),
    ]
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='going'
    )

    registration_notes = models.TextField(blank=True)
    registered_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    # Post-event data
    checked_in_at = models.DateTimeField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    rating = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="1-5 stars"
    )

    class Meta:
        unique_together = ['occurrence', 'user']
        indexes = [
            models.Index(fields=['occurrence', 'status']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['occurrence', 'user']),
        ]
        verbose_name = "Occurrence Attendee"
        verbose_name_plural = "Occurrence Attendees"

    def __str__(self):
        return f"{self.user} - {self.occurrence.effective_title} ({self.status})"

    def check_in(self):
        """Mark as checked in"""
        self.checked_in_at = timezone.now()
        self.status = 'attended'
        self.save()


# ============================================================================
# DECORATOR SYSTEM - Normalized decorators for events
# ============================================================================

class Decorator(BaseModel):
    """
    Normalized decorator definitions.
    Replaces boolean fields with flexible, extensible system.

    Inherits from BaseModel:
    - id (UUID)
    - created_at, updated_at

    Note: Eventually may merge with Group decorators into unified system.
    For now, separate implementation scoped to events.
    """

    slug = models.SlugField(
        unique=True,
        help_text="Machine name: is_potluck, is_open_to_public"
    )
    name = models.CharField(
        max_length=100,
        help_text="Display name: Potluck, Open to Public"
    )
    icon = models.CharField(
        max_length=10,
        help_text="Emoji icon: 🍽️, 🌐"
    )
    description = models.TextField(blank=True)

    # Decorator behavior
    has_context_data = models.BooleanField(
        default=False,
        help_text="Does this decorator store additional context (instructions, etc.)?"
    )
    is_active = models.BooleanField(default=True)

    # Display order for UI
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Decorator"
        verbose_name_plural = "Decorators"
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.icon} {self.name}"


class EventDecoratorManager(models.Manager):
    """Manager for EventDecorator assignments"""

    def for_decorator_slug(self, slug):
        """Get all event decorator assignments for a specific decorator"""
        return self.filter(
            decorator__slug=slug,
            decorator__is_active=True
        )

    def with_context(self):
        """Get assignments that have context data"""
        return self.exclude(context_data={})


class EventDecorator(BaseModel):
    """
    Assignment of decorators to events with optional context data.
    Replaces the boolean mixin approach.

    Inherits from BaseModel:
    - id (UUID)
    - created_at, updated_at
    """

    objects = EventDecoratorManager()

    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name='decorator_assignments'
    )
    decorator = models.ForeignKey(
        Decorator,
        on_delete=models.CASCADE,
        related_name='event_assignments'
    )

    # Context data for decorator-specific information
    context_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Decorator-specific data: instructions, learning outcomes, etc."
    )

    class Meta:
        unique_together = ['event', 'decorator']
        indexes = [
            models.Index(fields=["decorator", "event"]),
            models.Index(fields=["event"]),
        ]
        verbose_name = "Event Decorator Assignment"
        verbose_name_plural = "Event Decorator Assignments"

    def __str__(self):
        return f"{self.event.title} - {self.decorator.name}"