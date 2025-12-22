# almanac/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import (
    Event, EventSeries, EventOccurrence, Decorator, EventDecorator,
    GatheringExtension, OccurrenceAttendee, EventFollower
)


@admin.register(Decorator)
class DecoratorAdmin(admin.ModelAdmin):
    """Admin for event decorators (characteristics like 'potluck', 'open to public')"""
    list_display = ['icon_display', 'name', 'slug', 'is_active', 'has_context_data', 'sort_order', 'event_count']
    list_filter = ['is_active', 'has_context_data']
    search_fields = ['name', 'slug', 'description']
    ordering = ['sort_order', 'name']
    prepopulated_fields = {'slug': ('name',)}

    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'slug', 'icon', 'description')
        }),
        ('Behavior', {
            'fields': ('has_context_data', 'is_active', 'sort_order')
        }),
    )

    def icon_display(self, obj):
        """Display icon with name"""
        return f"{obj.icon} {obj.name}"
    icon_display.short_description = 'Decorator'

    def event_count(self, obj):
        """Count of events using this decorator"""
        count = obj.event_assignments.count()
        return format_html('<b>{}</b>', count)
    event_count.short_description = 'Events'


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """Admin for events"""
    list_display = ['title', 'event_format', 'status_badge', 'published_at', 'location', 'sponsor_display', 'author', 'next_occurrence_display']
    list_filter = ['status', 'event_format', 'registration_required', 'created_at']
    search_fields = ['title', 'description', 'location']
    readonly_fields = ['created_at', 'updated_at', 'published_at', 'sponsor_display', 'next_occurrence_link', 'series_link']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'description', 'location', 'event_format')
        }),
        ('Capacity & Registration', {
            'fields': ('max_attendees', 'registration_required', 'registration_deadline_hours')
        }),
        ('Publishing', {
            'fields': ('status', 'published_at', 'author')
        }),
        ('Relationships', {
            'fields': ('sponsor_display', 'series_link', 'next_occurrence_link'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def status_badge(self, obj):
        """Display status with color coding"""
        colors = {
            'draft': '#FFA500',
            'published': '#28A745',
            'archived': '#6C757D',
        }
        color = colors.get(obj.status, '#6C757D')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper()
        )
    status_badge.short_description = 'Status'

    def next_occurrence_display(self, obj):
        """Display next occurrence time"""
        next_occ = obj.next_occurrence
        if next_occ:
            return next_occ.start.strftime('%Y-%m-%d %H:%M')
        return '—'
    next_occurrence_display.short_description = 'Next Occurrence'

    def series_link(self, obj):
        """Link to related series"""
        if hasattr(obj, 'series') and obj.series:
            url = reverse('admin:almanac_eventseries_change', args=[obj.series.id])
            return format_html('<a href="{}">View Series</a>', url)
        return '—'
    series_link.short_description = 'Series'

    def next_occurrence_link(self, obj):
        """Link to next occurrence"""
        next_occ = obj.next_occurrence
        if next_occ:
            url = reverse('admin:almanac_eventoccurrence_change', args=[next_occ.id])
            return format_html('<a href="{}">{}</a>', url, next_occ.start.strftime('%Y-%m-%d %H:%M'))
        return '—'
    next_occurrence_link.short_description = 'Next Occurrence'


@admin.register(EventSeries)
class EventSeriesAdmin(admin.ModelAdmin):
    """Admin for event series (scheduling unit)"""
    list_display = ['title', 'event_link', 'timezone', 'duration_display', 'is_active', 'is_recurring', 'occurrence_count']
    list_filter = ['is_active', 'timezone']
    search_fields = ['title', 'event__title']
    readonly_fields = ['created_at', 'updated_at', 'sponsor_display', 'event_link', 'next_occurrence_display']

    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'event_link', 'sponsor_display')
        }),
        ('Scheduling', {
            'fields': ('timezone', 'default_duration_minutes', 'rrule')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def duration_display(self, obj):
        """Display duration in hours:minutes format"""
        hours = obj.default_duration_minutes // 60
        minutes = obj.default_duration_minutes % 60
        if hours > 0:
            return f"{hours}h {minutes}m" if minutes else f"{hours}h"
        return f"{minutes}m"
    duration_display.short_description = 'Duration'

    def occurrence_count(self, obj):
        """Count of occurrences"""
        total = obj.occurrences.count()
        upcoming = obj.occurrences.filter(start__gte=timezone.now(), is_cancelled=False).count()
        return format_html('<b>{}</b> total / <b>{}</b> upcoming', total, upcoming)
    occurrence_count.short_description = 'Occurrences'

    def event_link(self, obj):
        """Link to related event"""
        if obj.event:
            url = reverse('admin:almanac_event_change', args=[obj.event.id])
            return format_html('<a href="{}">{}</a>', url, obj.event.title)
        return '—'
    event_link.short_description = 'Event'

    def next_occurrence_display(self, obj):
        """Display next occurrence"""
        next_occ = obj.next_occurrence
        if next_occ:
            url = reverse('admin:almanac_eventoccurrence_change', args=[next_occ.id])
            return format_html('<a href="{}">{}</a>', url, next_occ.start.strftime('%Y-%m-%d %H:%M'))
        return '—'
    next_occurrence_display.short_description = 'Next Occurrence'


@admin.register(EventOccurrence)
class EventOccurrenceAdmin(admin.ModelAdmin):
    """Admin for individual event occurrences"""
    list_display = ['occurrence_display', 'series_link', 'start', 'end', 'status_display', 'attendee_count_display']
    list_filter = ['is_cancelled', 'start']
    search_fields = ['series__title', 'title_override', 'series__event__title']
    readonly_fields = ['created_at', 'duration_hours', 'is_past', 'is_happening_now', 'effective_title', 'effective_location', 'series_link', 'event_link']
    date_hierarchy = 'start'

    fieldsets = (
        ('Basic Info', {
            'fields': ('series_link', 'event_link', 'effective_title', 'effective_location')
        }),
        ('Timing', {
            'fields': ('recurrence_id', 'start', 'end', 'duration_hours')
        }),
        ('Overrides', {
            'fields': ('title_override', 'location_override'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_cancelled', 'cancellation_reason', 'is_past', 'is_happening_now')
        }),
        ('Post-Event', {
            'fields': ('notes', 'actual_attendance'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def occurrence_display(self, obj):
        """Display occurrence title"""
        title = obj.title_override or obj.series.title
        return title[:50] + '...' if len(title) > 50 else title
    occurrence_display.short_description = 'Title'

    def status_display(self, obj):
        """Display status with indicators"""
        if obj.is_cancelled:
            return format_html('<span style="color: red;">⊗ CANCELLED</span>')
        elif obj.is_past:
            return format_html('<span style="color: gray;">✓ Past</span>')
        elif obj.is_happening_now:
            return format_html('<span style="color: green;">● NOW</span>')
        else:
            return format_html('<span style="color: blue;">◷ Upcoming</span>')
    status_display.short_description = 'Status'

    def attendee_count_display(self, obj):
        """Display attendee counts"""
        going = obj.attendees.filter(status='going').count()
        maybe = obj.attendees.filter(status='maybe').count()
        total = going + maybe

        if obj.series.event and obj.series.event.max_attendees:
            capacity = obj.series.event.max_attendees
            percentage = (going / capacity * 100) if capacity > 0 else 0
            color = '#28A745' if percentage < 80 else '#FFA500' if percentage < 100 else '#DC3545'
            return format_html(
                '<span style="color: {}"><b>{}</b> / {}</span> ({}% full)<br><small>{} going, {} maybe</small>',
                color, going, capacity, int(percentage), going, maybe
            )
        return format_html('<b>{}</b> total<br><small>{} going, {} maybe</small>', total, going, maybe)
    attendee_count_display.short_description = 'Attendees'

    def series_link(self, obj):
        """Link to series"""
        if obj.series:
            url = reverse('admin:almanac_eventseries_change', args=[obj.series.id])
            return format_html('<a href="{}">{}</a>', url, obj.series.title)
        return '—'
    series_link.short_description = 'Series'

    def event_link(self, obj):
        """Link to event"""
        if obj.series and obj.series.event:
            url = reverse('admin:almanac_event_change', args=[obj.series.event.id])
            return format_html('<a href="{}">{}</a>', url, obj.series.event.title)
        return '—'
    event_link.short_description = 'Event'


@admin.register(OccurrenceAttendee)
class OccurrenceAttendeeAdmin(admin.ModelAdmin):
    """Admin for RSVP/attendance records"""
    list_display = ['user', 'occurrence_link', 'status_badge', 'registered_at', 'checked_in_at', 'rating_display']
    list_filter = ['status', 'registered_at', 'checked_in_at']
    search_fields = ['user__username', 'user__email', 'occurrence__series__title', 'occurrence__series__event__title']
    readonly_fields = ['registered_at', 'created_at', 'updated_at', 'occurrence_link', 'event_link']
    date_hierarchy = 'registered_at'

    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'occurrence_link', 'event_link', 'status')
        }),
        ('Registration', {
            'fields': ('registered_at', 'registration_notes')
        }),
        ('Check-in', {
            'fields': ('checked_in_at',),
            'classes': ('collapse',)
        }),
        ('Feedback', {
            'fields': ('feedback', 'rating'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def status_badge(self, obj):
        """Display status with color coding"""
        colors = {
            'going': '#28A745',
            'maybe': '#FFC107',
            'not_going': '#6C757D',
            'attended': '#007BFF',
            'no_show': '#DC3545',
        }
        color = colors.get(obj.status, '#6C757D')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def rating_display(self, obj):
        """Display rating as stars"""
        if obj.rating:
            stars = '⭐' * obj.rating
            return format_html('<span title="{}/5">{}</span>', obj.rating, stars)
        return '—'
    rating_display.short_description = 'Rating'

    def occurrence_link(self, obj):
        """Link to occurrence"""
        if obj.occurrence:
            url = reverse('admin:almanac_eventoccurrence_change', args=[obj.occurrence.id])
            return format_html('<a href="{}">{}</a>', url, obj.occurrence.effective_title)
        return '—'
    occurrence_link.short_description = 'Occurrence'

    def event_link(self, obj):
        """Link to event"""
        if obj.occurrence and obj.occurrence.series and obj.occurrence.series.event:
            event = obj.occurrence.series.event
            url = reverse('admin:almanac_event_change', args=[event.id])
            return format_html('<a href="{}">{}</a>', url, event.title)
        return '—'
    event_link.short_description = 'Event'


@admin.register(EventFollower)
class EventFollowerAdmin(admin.ModelAdmin):
    """Admin for event followers"""
    list_display = ['user', 'event_link', 'follow_type_badge', 'notify_new_occurrences', 'notify_changes', 'created_at']
    list_filter = ['follow_type', 'notify_new_occurrences', 'notify_changes', 'created_at']
    search_fields = ['user__username', 'user__email', 'event__title']
    readonly_fields = ['created_at', 'updated_at', 'event_link']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'event_link', 'follow_type')
        }),
        ('Notifications', {
            'fields': ('notify_new_occurrences', 'notify_changes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def follow_type_badge(self, obj):
        """Display follow type with styling"""
        colors = {
            'following': '#007BFF',
            'interested': '#FFC107',
            'organizer': '#28A745',
        }
        color = colors.get(obj.follow_type, '#6C757D')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_follow_type_display()
        )
    follow_type_badge.short_description = 'Follow Type'

    def event_link(self, obj):
        """Link to event"""
        if obj.event:
            url = reverse('admin:almanac_event_change', args=[obj.event.id])
            return format_html('<a href="{}">{}</a>', url, obj.event.title)
        return '—'
    event_link.short_description = 'Event'


@admin.register(GatheringExtension)
class GatheringExtensionAdmin(admin.ModelAdmin):
    """Admin for gathering-specific event data"""
    list_display = ['event_link', 'accommodation_available', 'meals_included', 'created_at']
    list_filter = ['accommodation_available', 'meals_included']
    search_fields = ['event__title']
    readonly_fields = ['created_at', 'updated_at', 'event_link']

    fieldsets = (
        ('Event', {
            'fields': ('event_link',)
        }),
        ('Logistics', {
            'fields': ('accommodation_available', 'meals_included')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def event_link(self, obj):
        """Link to event"""
        if obj.event:
            url = reverse('admin:almanac_event_change', args=[obj.event.id])
            return format_html('<a href="{}">{}</a>', url, obj.event.title)
        return '—'
    event_link.short_description = 'Event'


@admin.register(EventDecorator)
class EventDecoratorAdmin(admin.ModelAdmin):
    """Admin for event decorator assignments"""
    list_display = ['event_link', 'decorator_display', 'has_context', 'created_at']
    list_filter = ['decorator', 'created_at']
    search_fields = ['event__title', 'decorator__name', 'decorator__slug']
    readonly_fields = ['created_at', 'updated_at', 'event_link']

    fieldsets = (
        ('Assignment', {
            'fields': ('event_link', 'decorator')
        }),
        ('Context Data', {
            'fields': ('context_data',),
            'description': 'Decorator-specific JSON data (instructions, learning outcomes, etc.)'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def decorator_display(self, obj):
        """Display decorator with icon"""
        return f"{obj.decorator.icon} {obj.decorator.name}"
    decorator_display.short_description = 'Decorator'

    def has_context(self, obj):
        """Show if context data exists"""
        return bool(obj.context_data and obj.context_data != {})
    has_context.boolean = True
    has_context.short_description = 'Has Context'

    def event_link(self, obj):
        """Link to event"""
        if obj.event:
            url = reverse('admin:almanac_event_change', args=[obj.event.id])
            return format_html('<a href="{}">{}</a>', url, obj.event.title)
        return '—'
    event_link.short_description = 'Event'
