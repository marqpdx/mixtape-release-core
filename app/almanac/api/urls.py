# almanac/api/urls.py

"""
Mixtape Almanac URL Configuration
Explicit, polymorphic API routes for Event management
Group-scoped and site-wide patterns following threadworks pattern
No trailing slashes - follows DRF convention
"""

from django.urls import path, include
from . import views

app_name = 'almanac'

# parent: api/almanac/

# =============================================================================
# SITE-WIDE EVENT ENDPOINTS
# =============================================================================

site_almanac_patterns = [

    # Event CRUD
    path('', views.EventListCreateView.as_view(), name='event-list-create'),
    path('<uuid:event_id>', views.EventDetailView.as_view(), name='event-detail'),
    path('<uuid:event_id>/publish', views.EventPublishView.as_view(), name='event-publish'),
    path('<uuid:event_id>/unpublish', views.EventUnpublishView.as_view(), name='event-unpublish'),

    # Event Actions
    path('<uuid:event_id>/rsvp', views.EventRSVPView.as_view(), name='event-rsvp'),
    path('<uuid:event_id>/follow', views.EventFollowView.as_view(), name='event-follow'),
    path('<uuid:event_id>/attendees', views.EventAttendeesView.as_view(), name='event-attendees'),
    path('<uuid:event_id>/rsvp-breakdown', views.EventRSVPBreakdownView.as_view(), name='event-rsvp-breakdown'),  # ← ADD THIS

    # Management
    path('<uuid:event_id>/sync-rsvps', views.EventSyncRsvpsView.as_view(), name='event-sync-rsvps'),
    path('<uuid:event_id>/analytics', views.EventAnalyticsView.as_view(), name='event-analytics'),
]

# =============================================================================
# GROUP-SCOPED EVENT ENDPOINTS
# =============================================================================

group_almanac_patterns = [

    # Event CRUD - group-specific
    path('', views.GroupEventListCreateView.as_view(), name='group-event-list-create'),

    # Group-scoped Calendar Occurrences (MUST come before <slug:event_slug>)
    path('calendar', views.GroupCalendarOccurrencesView.as_view(), name='group-calendar-occurrences'),

    # Event detail and actions (dynamic slug patterns come after specific paths)
    path('<slug:event_slug>', views.GroupEventDetailView.as_view(), name='group-event-detail'),
    path('<slug:event_slug>/publish', views.GroupEventPublishView.as_view(), name='group-event-publish'),
    path('<slug:event_slug>/unpublish', views.GroupEventUnpublishView.as_view(), name='group-event-unpublish'),
    path('<slug:event_slug>/rsvp', views.GroupEventRSVPView.as_view(), name='group-event-rsvp'),
    path('<slug:event_slug>/follow', views.GroupEventFollowView.as_view(), name='group-event-follow'),
    path('<slug:event_slug>/attendees', views.GroupEventAttendeesView.as_view(), name='group-event-attendees'),
    path('<slug:event_slug>/attendees/<str:attendee_id>/check-in', views.GroupEventAttendeeCheckInView.as_view(), name='group-event-attendee-check-in'),
    path('<slug:event_slug>/occurrences', views.GroupEventOccurrencesView.as_view(), name='group-event-occurrences'),
    path('<slug:event_slug>/occurrences/<str:occurrence_id>', views.GroupEventOccurrenceUpdateView.as_view(), name='group-event-occurrence-update'),
    path('<slug:event_slug>/occurrences/<str:occurrence_id>/attendees', views.GroupEventOccurrenceAttendeesView.as_view(), name='group-event-occurrence-attendees'),
    path('<slug:event_slug>/occurrences/<str:occurrence_id>/cancel', views.GroupEventOccurrenceCancelView.as_view(), name='group-event-occurrence-cancel'),
    path('<slug:event_slug>/rsvp-breakdown', views.GroupEventRSVPBreakdownView.as_view(), name='group-event-rsvp-breakdown'),
    path('<slug:event_slug>/sync-rsvps', views.GroupEventSyncRsvpsView.as_view(), name='group-event-sync-rsvps'),
    path('<slug:event_slug>/analytics', views.GroupEventAnalyticsView.as_view(), name='group-event-analytics'),
]


# =============================================================================
# OCCURRENCE ENDPOINTS (Site-wide)
# =============================================================================

occurrence_patterns = [
    path('', views.OccurrenceListView.as_view(), name='occurrence-list'),
    path('<int:occurrence_id>', views.OccurrenceDetailView.as_view(), name='occurrence-detail'),
    path('<int:occurrence_id>/rsvp', views.OccurrenceRSVPView.as_view(), name='occurrence-rsvp'),
    path('<int:occurrence_id>/cancel-rsvp', views.OccurrenceCancelRSVPView.as_view(), name='occurrence-cancel-rsvp'),
]


# =============================================================================
# MAIN URLPATTERNS
# =============================================================================

urlpatterns = [
    # Site-wide events
    path('events/', include(site_almanac_patterns)),

    # Occurrences
    path('occurrences/', include(occurrence_patterns)),

    # =============================================================================
    # CALENDAR ENDPOINTS - Primary frontend integration
    # =============================================================================

    path('calendar', views.CalendarOccurrencesView.as_view(), name='calendar-occurrences'),
    path('calendar/my', views.MyCalendarOccurrencesView.as_view(), name='my-calendar-occurrences'),

    # =============================================================================
    # UTILITY ENDPOINTS
    # =============================================================================

    path('decorators', views.DecoratorListView.as_view(), name='decorator-list'),
    path('my-events-summary', views.MyEventsSummaryView.as_view(), name='my-events-summary'),
    path('bulk-rsvp', views.BulkRSVPView.as_view(), name='bulk-rsvp'),
]

# =============================================================================
# EXAMPLE USAGE & FRONTEND INTEGRATION (Updated)
# =============================================================================

"""
COMPLETE API ENDPOINT REFERENCE (No trailing slashes):

SITE-WIDE EVENTS:
   GET    /api/almanac/events                     # List events
   POST   /api/almanac/events                     # Create event
   GET    /api/almanac/events/{id}                # Event details
   PUT    /api/almanac/events/{id}                # Update event
   DELETE /api/almanac/events/{id}                # Archive event

GROUP-SCOPED EVENTS:
   GET    /api/groups/:slug/events                # List group events
   POST   /api/groups/:slug/events                # Create group event
   GET    /api/groups/:slug/events/{id}           # Event details
   PUT    /api/groups/:slug/events/{id}           # Update event
   DELETE /api/groups/:slug/events/{id}           # Archive event

EVENT ACTIONS:
   POST   /api/groups/:slug/events/{id}/publish   # Publish event
   POST   /api/groups/:slug/events/{id}/unpublish # Unpublish event
   POST   /api/groups/:slug/events/{id}/rsvp      # RSVP to series
   POST   /api/groups/:slug/events/{id}/follow    # Follow event
   DELETE /api/groups/:slug/events/{id}/follow    # Unfollow event
   GET    /api/groups/:slug/events/{id}/attendees # Get attendees list ✨ NEW
   GET    /api/groups/:slug/events/{id}/rsvp-breakdown # Get RSVP counts ✨ NEW

OCCURRENCE MANAGEMENT:
   GET    /api/almanac/occurrences                # List occurrences
   GET    /api/almanac/occurrences/{id}           # Occurrence details
   POST   /api/almanac/occurrences/{id}/rsvp      # RSVP to occurrence
   DELETE /api/almanac/occurrences/{id}/cancel-rsvp # Cancel RSVP

CALENDAR INTEGRATION:
   GET    /api/almanac/calendar?start=...&end=...
   GET    /api/almanac/calendar/my?start=...&end=...

UTILITY:
   GET    /api/almanac/decorators
   GET    /api/almanac/my-events-summary
   POST   /api/almanac/bulk-rsvp

MANAGEMENT:
   POST   /api/groups/:slug/events/{id}/sync-rsvps
   GET    /api/groups/:slug/events/{id}/analytics
"""
