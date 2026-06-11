# almanac/producers.py
"""Activity producers for Almanac (Event) events."""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def _group_from_event(event):
    """Return the sponsoring Group if event is group-sponsored, else None."""
    from django.contrib.contenttypes.models import ContentType
    from groups.models import Group
    group_ct = ContentType.objects.get_for_model(Group)
    if event.sponsor_content_type_id == group_ct.id and event.sponsor_object_id:
        try:
            return Group.objects.get(pk=event.sponsor_object_id, is_active=True)
        except Group.DoesNotExist:
            pass
    return None


def on_almanac_event_published(*, event, actor_user):
    """Notify group members when a new event is published to the Almanac."""
    group = _group_from_event(event)
    if not group:
        return

    at = _ensure_activity_type(
        code="group.almanac.event_published",
        label="New Event Published",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(actor_user),
        actor_id=_id(actor_user),
        actor_label="user",
        object_content_type=_ct(event),
        object_id=_id(event),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="published",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "event_title": event.title,
            "event_slug": event.slug or "",
            "event_format": event.event_format,
        },
        dedupe_key=f"{at.code}:{_id(event)}",
        aggregate_key=f"almanac:{_id(group)}:{timezone.now():%Y%m%d}",
        audience={"type": "group_members", "group_id": str(_id(group)), "exclude_actor": True},
        occurs_at=timezone.now(),
    )
    _maybe_bubble_circle(group=group, actor_user=actor_user)


def on_almanac_occurrence_updated(*, occurrence, event, actor_user):
    """Notify group members when an event occurrence is added or its timing changes."""
    group = _group_from_event(event)
    if not group:
        return

    at = _ensure_activity_type(
        code="group.almanac.occurrence_updated",
        label="Event Time Updated",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(actor_user),
        actor_id=_id(actor_user),
        actor_label="user",
        object_content_type=_ct(occurrence),
        object_id=_id(occurrence),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="updated",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "event_title": event.title,
            "event_slug": event.slug or "",
            "occurrence_start": occurrence.start.isoformat(),
        },
        # Daily dedupe per occurrence — if rescheduled twice in a day, rolls up
        dedupe_key=f"{at.code}:{_id(occurrence)}:{timezone.now():%Y%m%d}",
        aggregate_key=f"almanac:{_id(group)}:{timezone.now():%Y%m%d}",
        audience={"type": "group_members", "group_id": str(_id(group)), "exclude_actor": True},
        occurs_at=timezone.now(),
    )
    _maybe_bubble_circle(group=group, actor_user=actor_user)


def _maybe_bubble_circle(*, group, actor_user):
    from groups.producers import on_circle_activity
    on_circle_activity(circle=group, actor_user=actor_user)
