# profiles/producers.py
"""Activity producers for UserProfile events."""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def on_profile_updated(*, profile, actor_user):
    """
    Notify groupmates in each of the user's groups when they update their profile.
    Emits one Action per group so the update appears in each group's activity context.
    Daily aggregate key prevents multiple saves in a day from spamming.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType
    from groups.models import Group
    from groups.models.membership import GroupMembership
    from groups.producers import on_circle_activity

    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)

    memberships = GroupMembership.objects.filter(
        member_content_type=user_ct,
        member_object_id=actor_user.pk,
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
    ).select_related("group")

    at = _ensure_activity_type(
        code="group.member.profile_updated",
        label="Member Updated Profile",
        default_channel="activity",
        default_priority="low",
        suppressible=True,
    )

    for membership in memberships:
        group = membership.group
        _create_action_and_outbox(
            actor_content_type=_ct(actor_user),
            actor_id=_id(actor_user),
            actor_label="user",
            object_content_type=_ct(profile),
            object_id=_id(profile),
            context_content_type=_ct(group),
            context_id=_id(group),
            activity_type=at,
            verb="updated_profile",
            activity_code=at.code,
            channel=at.default_channel,
            priority=at.default_priority,
            metadata={"username": actor_user.username},
            # Daily dedupe per user per group
            dedupe_key=f"{at.code}:{_id(actor_user)}:{_id(group)}:{timezone.now():%Y%m%d}",
            aggregate_key=f"profile_update:{_id(actor_user)}:{_id(group)}:{timezone.now():%Y%m%d}",
            audience={"type": "group_members", "group_id": str(_id(group)), "exclude_actor": True},
            occurs_at=timezone.now(),
        )
        on_circle_activity(circle=group, actor_user=actor_user)
