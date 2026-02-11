# groups/services/ownership.py
"""
Service layer for time-delayed ownership changes.

Three core operations:
  - create_ownership_request: owner initiates a change (delayed)
  - cancel_ownership_request: any owner cancels a pending request
  - execute_ownership_request: system executes after delay expires
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from groups.models.group import Group
from groups.models.membership import GroupMembership
from groups.models.ownership import (
    OwnershipAction,
    OwnershipChangeRequest,
    OwnershipRequestStatus,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_active_owners(group) -> list[GroupMembership]:
    """Return active owner memberships for a group (user members only)."""
    user_ct = ContentType.objects.get_for_model(User)
    return list(
        GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            is_active=True,
            roles__contains=["owner"],
        )
    )


def _get_user_membership(group, user) -> GroupMembership | None:
    """Get active user membership in a group."""
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.pk,
        is_active=True,
    ).first()


def _assert_is_active_owner(group, user) -> GroupMembership:
    """Assert user is an active owner of the group. Returns the membership."""
    membership = _get_user_membership(group, user)
    if not membership or not membership.is_owner():
        raise PermissionError(f"User {user} is not an active owner of {group}")
    return membership


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_ownership_request(
    group: Group,
    requested_by: User,
    action: str,
    target_user: User,
) -> OwnershipChangeRequest:
    """
    Create a time-delayed ownership change request.

    Only active owners can create requests. The request will execute
    after group.ownership_change_delay_seconds.

    Raises:
        PermissionError: if requested_by is not an active owner
        ValueError: if action is invalid or request is a duplicate
    """
    _assert_is_active_owner(group, requested_by)

    # Validate action
    valid_actions = [c[0] for c in OwnershipAction.choices]
    if action not in valid_actions:
        raise ValueError(f"Invalid action: {action}. Must be one of {valid_actions}")

    # Check for duplicate pending request
    if OwnershipChangeRequest.objects.filter(
        group=group,
        action=action,
        target_user=target_user,
        status=OwnershipRequestStatus.PENDING,
    ).exists():
        raise ValueError(
            f"A pending {action} request for this user already exists"
        )

    # Action-specific validation
    target_membership = _get_user_membership(group, target_user)

    if action == OwnershipAction.ADD_OWNER:
        if not target_membership:
            raise ValueError("Target user is not a member of this group")
        if target_membership.is_owner():
            raise ValueError("Target user is already an owner")

    elif action == OwnershipAction.REMOVE_OWNER:
        if not target_membership or not target_membership.is_owner():
            raise ValueError("Target user is not an owner of this group")

    elif action == OwnershipAction.DEMOTE_OWNER:
        if not target_membership or not target_membership.is_owner():
            raise ValueError("Target user is not an owner of this group")

    elif action == OwnershipAction.TRANSFER_OWNERSHIP:
        if not target_membership:
            raise ValueError("Target user is not a member of this group")
        if target_membership.is_owner():
            raise ValueError("Target user is already an owner")

    elif action == OwnershipAction.SET_ESCROW_OWNER:
        # Target doesn't need to be a current member
        pass

    # Compute execution time
    execute_after = timezone.now() + timedelta(
        seconds=group.ownership_change_delay_seconds
    )

    # Snapshot current owners
    owners = get_active_owners(group)
    snapshot = {
        "owner_ids": [str(m.member_object_id) for m in owners],
        "escrow_owner_id": str(group.escrow_owner_id) if group.escrow_owner_id else None,
    }

    request = OwnershipChangeRequest.objects.create(
        group=group,
        action=action,
        target_user=target_user,
        requested_by=requested_by,
        execute_after=execute_after,
        snapshot=snapshot,
    )

    # Fire notification
    from groups.producers import on_ownership_change_requested
    on_ownership_change_requested(request=request, group=group)

    return request


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def cancel_ownership_request(
    request: OwnershipChangeRequest,
    canceled_by: User,
) -> OwnershipChangeRequest:
    """
    Cancel a pending ownership change request.

    Any active owner of the group can cancel.

    Raises:
        PermissionError: if canceled_by is not an active owner
        ValueError: if request is not PENDING
    """
    _assert_is_active_owner(request.group, canceled_by)

    if request.status != OwnershipRequestStatus.PENDING:
        raise ValueError(
            f"Cannot cancel request with status {request.status}"
        )

    request.status = OwnershipRequestStatus.CANCELED
    request.canceled_by = canceled_by
    request.canceled_at = timezone.now()
    request.save(update_fields=["status", "canceled_by", "canceled_at", "updated_at"])

    from groups.producers import on_ownership_change_canceled
    on_ownership_change_canceled(request=request, group=request.group)

    return request


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

@transaction.atomic
def execute_ownership_request(request: OwnershipChangeRequest) -> OwnershipChangeRequest:
    """
    Execute an ownership change request.

    Called by the periodic Celery task when execute_after has passed.
    Uses select_for_update to prevent double execution.

    Returns the updated request (EXECUTED or FAILED).
    """
    # Lock the request row
    request = (
        OwnershipChangeRequest.objects
        .select_for_update()
        .select_related("group", "target_user", "requested_by")
        .get(pk=request.pk)
    )

    # Re-check preconditions
    if request.status != OwnershipRequestStatus.PENDING:
        return request

    now = timezone.now()
    if now < request.execute_after:
        return request

    group = request.group
    target_user = request.target_user
    action = request.action

    try:
        if action == OwnershipAction.ADD_OWNER:
            _execute_add_owner(group, target_user)

        elif action == OwnershipAction.REMOVE_OWNER:
            _execute_remove_owner(group, target_user)

        elif action == OwnershipAction.DEMOTE_OWNER:
            _execute_demote_owner(group, target_user)

        elif action == OwnershipAction.TRANSFER_OWNERSHIP:
            _execute_transfer_ownership(group, request.requested_by, target_user)

        elif action == OwnershipAction.SET_ESCROW_OWNER:
            _execute_set_escrow_owner(group, target_user)

        else:
            raise ValueError(f"Unknown action: {action}")

        request.status = OwnershipRequestStatus.EXECUTED
        request.executed_at = now
        request.save(update_fields=["status", "executed_at", "updated_at"])

        from groups.producers import on_ownership_change_executed
        on_ownership_change_executed(request=request, group=group)

    except Exception as exc:
        request.status = OwnershipRequestStatus.FAILED
        request.failure_reason = str(exc)
        request.executed_at = now
        request.save(update_fields=["status", "failure_reason", "executed_at", "updated_at"])

        from groups.producers import on_ownership_change_failed
        on_ownership_change_failed(request=request, group=group)

    return request


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------

def _execute_add_owner(group, target_user):
    """Grant owner + admin roles to target user."""
    membership = _get_user_membership(group, target_user)
    if not membership:
        raise ValueError("Target user is no longer a member of this group")
    if membership.is_owner():
        raise ValueError("Target user is already an owner")
    membership.grant_role("admin")
    membership.grant_role("owner")


def _execute_remove_owner(group, target_user):
    """Revoke owner role from target (keeps admin + member)."""
    membership = _get_user_membership(group, target_user)
    if not membership or not membership.is_owner():
        raise ValueError("Target user is not an owner")
    _ensure_at_least_one_owner_remains(group, target_user)
    membership.revoke_role("owner")


def _execute_demote_owner(group, target_user):
    """Revoke owner and admin roles (back to member)."""
    membership = _get_user_membership(group, target_user)
    if not membership or not membership.is_owner():
        raise ValueError("Target user is not an owner")
    _ensure_at_least_one_owner_remains(group, target_user)
    membership.revoke_role("owner")
    membership.revoke_role("admin")


def _execute_transfer_ownership(group, requester, target_user):
    """Remove owner from requester, add owner to target (atomic swap)."""
    requester_membership = _get_user_membership(group, requester)
    if not requester_membership or not requester_membership.is_owner():
        raise ValueError("Requester is no longer an owner")

    target_membership = _get_user_membership(group, target_user)
    if not target_membership:
        raise ValueError("Target user is no longer a member of this group")

    # Add owner to target first (so we never have zero owners)
    target_membership.grant_role("admin")
    target_membership.grant_role("owner")

    # Then remove from requester
    requester_membership.revoke_role("owner")


def _execute_set_escrow_owner(group, target_user):
    """Set the group's escrow owner."""
    group.escrow_owner = target_user
    group.save(update_fields=["escrow_owner", "updated_at"])


def _ensure_at_least_one_owner_remains(group, user_being_removed):
    """Raise if removing this user would leave zero owners."""
    owners = get_active_owners(group)
    remaining = [
        m for m in owners
        if str(m.member_object_id) != str(user_being_removed.pk)
    ]
    if len(remaining) < 1:
        raise ValueError(
            "Cannot remove the last owner. Transfer ownership first or add another owner."
        )
