# curation/producers.py
"""Activity producers for Collection events."""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def _group_from_sponsor(obj):
    """Return the sponsoring Group if sponsor is a Group, else None."""
    from django.contrib.contenttypes.models import ContentType
    from groups.models import Group
    group_ct = ContentType.objects.get_for_model(Group)
    if obj.sponsor_content_type_id == group_ct.id and obj.sponsor_object_id:
        try:
            return Group.objects.get(pk=obj.sponsor_object_id, is_active=True)
        except Group.DoesNotExist:
            pass
    return None


def on_collection_item_added(*, collection, item, actor_user):
    """Notify group members when a new item is added to a Collection."""
    group = _group_from_sponsor(collection)
    if not group:
        return

    at = _ensure_activity_type(
        code="group.collection.item_added",
        label="Item Added to Collection",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(actor_user),
        actor_id=_id(actor_user),
        actor_label="user",
        object_content_type=_ct(item),
        object_id=_id(item),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="added",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "collection_title": collection.title,
            "item_title": item.title or "",
        },
        dedupe_key=f"{at.code}:{_id(item)}",
        aggregate_key=f"collection:{_id(collection)}:{timezone.now():%Y%m%d}",
        audience={"type": "group_members", "group_id": str(_id(group)), "exclude_actor": True},
        occurs_at=timezone.now(),
    )
    _maybe_bubble_circle(group=group, actor_user=actor_user)


def on_collection_updated(*, collection, actor_user):
    """Notify group members when a Collection's metadata is edited."""
    group = _group_from_sponsor(collection)
    if not group:
        return

    at = _ensure_activity_type(
        code="group.collection.updated",
        label="Collection Updated",
        default_channel="activity",
        default_priority="low",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(actor_user),
        actor_id=_id(actor_user),
        actor_label="user",
        object_content_type=_ct(collection),
        object_id=_id(collection),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="updated",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={"collection_title": collection.title},
        # Daily dedupe: one notification per collection per day per recipient
        dedupe_key=f"{at.code}:{_id(collection)}:{timezone.now():%Y%m%d}",
        aggregate_key=f"collection_update:{_id(collection)}:{timezone.now():%Y%m%d}",
        audience={"type": "group_members", "group_id": str(_id(group)), "exclude_actor": True},
        occurs_at=timezone.now(),
    )
    _maybe_bubble_circle(group=group, actor_user=actor_user)


def _maybe_bubble_circle(*, group, actor_user):
    from groups.producers import on_circle_activity
    on_circle_activity(circle=group, actor_user=actor_user)
