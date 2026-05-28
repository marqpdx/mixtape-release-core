from __future__ import annotations

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def _dispatch_collaborator_ids(living_book, *, exclude_user=None) -> list[str]:
    """User IDs of all Dispatch collaborators on the trunk + trunk author."""
    ids = set()
    trunk = living_book.trunk
    if trunk.author_id:
        ids.add(str(trunk.author_id))
    try:
        from dispatch.models import DispatchContent
        dc = DispatchContent.objects.filter(writing_piece=trunk).first()
        if dc is not None:
            for collab in dc.collaborators.all():
                ids.add(str(collab.user_id))
    except Exception:
        pass
    if exclude_user is not None:
        ids.discard(str(exclude_user.pk))
    return list(ids)


def _group_editor_ids(living_book) -> list[str]:
    """User IDs of group editors (owner/admin/steward) for the LB sponsor group."""
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType
    from groups.models.membership import GroupMembership

    if not (
        living_book.sponsor_content_type_id
        and living_book.sponsor_content_type.model == "group"
    ):
        return []

    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    memberships = GroupMembership.objects.filter(
        group=living_book.sponsor,
        member_content_type=user_ct,
        is_active=True,
        is_banned=False,
        is_evicted=False,
    )
    return [
        str(m.member_object_id)
        for m in memberships
        if m.is_owner() or m.is_admin() or m.is_steward()
    ]


def on_branch_created(branch):
    lb = branch.living_book
    at = _ensure_activity_type(
        code="living_book.branch.created",
        label="Branch Created",
        default_channel="system",
        default_priority="low",
        suppressible=True,
    )
    editor_ids = _group_editor_ids(lb)
    if not editor_ids:
        return
    _create_action_and_outbox(
        actor_content_type=_ct(branch.created_by),
        actor_id=_id(branch.created_by),
        actor_label="user",
        object_content_type=_ct(branch),
        object_id=_id(branch),
        context_content_type=_ct(lb),
        context_id=_id(lb),
        activity_type=at,
        verb="created",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={"anchor_node_id": str(branch.anchor_node_id)},
        dedupe_key=f"{at.code}:{_id(branch)}",
        aggregate_key=f"lb_branch:{_id(lb)}",
        audience={"type": "users", "ids": editor_ids, "exclude_actor": True},
    )


def on_prompt_sent(branch, *, sent_by):
    lb = branch.living_book
    at = _ensure_activity_type(
        code="living_book.prompt.sent",
        label="Writing Prompt",
        default_channel="in_app",
        default_priority="normal",
        suppressible=True,
    )
    collaborator_ids = _dispatch_collaborator_ids(lb, exclude_user=sent_by)
    if not collaborator_ids:
        return
    _create_action_and_outbox(
        actor_content_type=_ct(sent_by),
        actor_id=_id(sent_by),
        actor_label="user",
        object_content_type=_ct(branch),
        object_id=_id(branch),
        context_content_type=_ct(lb),
        context_id=_id(lb),
        activity_type=at,
        verb="sent",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "prompt_text": branch.prompt_text,
            "due_date": branch.due_date.isoformat() if branch.due_date else None,
        },
        dedupe_key=f"{at.code}:{_id(branch)}",
        aggregate_key=f"lb_prompt:{_id(lb)}",
        audience={"type": "users", "ids": collaborator_ids, "exclude_actor": False},
    )


def on_leaf_cluster_attached(leaf_cluster):
    branch = leaf_cluster.branch
    lb = branch.living_book
    at = _ensure_activity_type(
        code="living_book.leaf_cluster.attached",
        label="Leaf Cluster Attached",
        default_channel="in_app",
        default_priority="low",
        suppressible=True,
    )
    # Notify branch creator + group editors, deduped
    recipient_ids = set(_group_editor_ids(lb))
    if branch.created_by_id:
        recipient_ids.add(str(branch.created_by_id))
    if leaf_cluster.created_by_id:
        recipient_ids.discard(str(leaf_cluster.created_by_id))
    if not recipient_ids:
        return
    _create_action_and_outbox(
        actor_content_type=_ct(leaf_cluster.created_by),
        actor_id=_id(leaf_cluster.created_by),
        actor_label="user",
        object_content_type=_ct(leaf_cluster),
        object_id=_id(leaf_cluster),
        context_content_type=_ct(branch),
        context_id=_id(branch),
        activity_type=at,
        verb="attached",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "piece_slug": getattr(leaf_cluster.piece, "slug", None),
            "media_type": leaf_cluster.media_type,
        },
        dedupe_key=f"{at.code}:{_id(leaf_cluster)}",
        aggregate_key=f"lb_leaf:{_id(branch)}",
        audience={"type": "users", "ids": list(recipient_ids), "exclude_actor": False},
    )
