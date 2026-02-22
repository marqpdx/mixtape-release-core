# earthlab/producers.py
"""Activity producers for EarthLab (course/lesson) events."""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def on_earthlab_course_updated(*, course, group, actor_user):
    """Notify group members when a course or lesson is created/updated."""
    at = _ensure_activity_type(
        code="group.earthlab.course_updated",
        label="Course or Lesson Updated",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(actor_user),
        actor_id=_id(actor_user),
        actor_label="user",
        object_content_type=_ct(course),
        object_id=_id(course),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="updated",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "course_title": course.title,
        },
        dedupe_key=f"{at.code}:{_id(course)}",
        aggregate_key=f"earthlab:{_id(group)}",
        audience={
            "type": "group_members",
            "group_id": str(_id(group)),
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )
