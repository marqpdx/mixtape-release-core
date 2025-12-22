# almanac/services.py or almanac/utils.py

from django.contrib.auth import get_user_model

User = get_user_model()

def sync_series_rsvps(event):
    """
    Sync RSVPs when new occurrences are added to a series.

    Use case: When RRULE expansion or manual occurrence addition happens,
    existing RSVPs should be extended to new occurrences.

    Args:
        event: Event instance

    Example:
        # After generating new occurrences from RRULE:
        new_occurrences = generate_rrule_occurrences(series)
        sync_series_rsvps(event)
    """
    # Find users who have RSVPed to any occurrence in this series
    rsvp_users = User.objects.filter(
        occurrence_attendances__occurrence__series=event.series,
        occurrence_attendances__status__in=["going", "maybe"]
    ).distinct()

    for user in rsvp_users:
        # Re-run fan-out to catch new occurrences
        from almanac.models import OccurrenceAttendee
        OccurrenceAttendee.objects.rsvp_to_entire_event(
            event,
            user,
            status="going"
        )