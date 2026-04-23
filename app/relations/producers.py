# relations/producers.py
"""
Event hooks for Relationship lifecycle events.

OQ-3 resolution (2026-04-22):
- Stackroom index update fires on all create/archive events.
- Notification fires on cross-author creates only (created_by != target object owner).
- Socket.io real-time update deferred to Phase 2.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def on_relationship_created(relationship) -> None:
    _fire_stackroom_index_update(relationship)
    _maybe_notify_target_owner(relationship)


def on_relationship_archived(relationship) -> None:
    _fire_stackroom_index_update(relationship)


# -------------------------------------------------------------------------
# Stackroom index update
# -------------------------------------------------------------------------

def _fire_stackroom_index_update(relationship) -> None:
    """
    Signal Stackroom to reindex both endpoints of this relationship.
    Stub: Stackroom MCP surface is built in Phase 5 (REL-10).
    """
    # TODO (REL-10): call switchboard/Stackroom reindex task for
    # relationship.source and relationship.target
    pass


# -------------------------------------------------------------------------
# Cross-author notification
# -------------------------------------------------------------------------

def _maybe_notify_target_owner(relationship) -> None:
    """
    Fire activity notification to the target object's owner when the
    relationship was created by a different user (cross-author).
    Only fires when created_by is set and differs from the target owner.
    """
    if relationship.created_by is None:
        return

    target_owner = _resolve_owner(relationship)
    if target_owner is None:
        return
    if target_owner.pk == relationship.created_by.pk:
        return

    try:
        _send_relationship_notification(relationship, target_owner)
    except Exception:
        logger.exception(
            "Failed to send cross-author relationship notification for %s",
            relationship.pk,
        )


def _resolve_owner(relationship):
    """
    Attempt to resolve the owner/author of the target object.
    Checks for common author fields: author, created_by, owner.
    Returns None when the target cannot be resolved or has no owner field.
    """
    target_model = relationship.target_content_type.model_class()
    if target_model is None:
        return None
    try:
        target_obj = target_model.objects.get(pk=relationship.target_object_id)
    except target_model.DoesNotExist:
        return None

    for attr in ("author", "created_by", "owner"):
        owner = getattr(target_obj, attr, None)
        if owner is not None:
            return owner
    return None


def _send_relationship_notification(relationship, target_owner) -> None:
    """
    Create an activity action notifying target_owner of the new relationship.
    Uses the existing activity producer pattern from activity.producers.
    """
    from activity.producers import (
        _create_action_and_outbox,
        _ct,
        _ensure_activity_type,
        _id,
    )

    at = _ensure_activity_type(
        code="relationship.created.cross_author",
        label="Linked your content",
        description="Someone linked to your content from another piece.",
    )

    _create_action_and_outbox(
        activity_type=at,
        actor_content_type=_ct(relationship.created_by),
        actor_object_id=_id(relationship.created_by),
        activity_code=at.code,
        audience={"type": "users", "ids": [str(target_owner.pk)]},
        context={
            "relationship_id": str(relationship.pk),
            "type_slug": relationship.relationship_type.slug,
        },
    )
