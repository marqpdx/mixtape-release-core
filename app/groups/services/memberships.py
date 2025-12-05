# groups/services/memberships.py
"""
Service functions for managing group memberships.
"""

from django.contrib.contenttypes.models import ContentType

from groups.models import GroupMembership


def ensure_user_membership(group, user, *, role="member", is_active=True):
    """
    Idempotently ensure `user` is a member of `group`.

    Args:
        group: Group instance
        user: User instance
        role: Role string - will be converted to roles array
              'admin' → ['member', 'admin']
              'steward' → ['member', 'steward']
              'member' → ['member']
        is_active: Whether membership is active

    Returns:
        GroupMembership instance

    Works with polymorphic membership fields:
      - member_content_type
      - member_object_id
    """
    ct = ContentType.objects.get_for_model(user)

    # Convert single role to roles array
    roles = _role_to_roles_array(role)

    m, created = GroupMembership.objects.get_or_create(
        group=group,
        member_content_type=ct,
        member_object_id=user.pk,
        defaults={
            "roles": roles,
            "is_active": is_active
        },
    )

    if not created:
        # Update existing membership if needed
        updated = False

        # Update roles if different
        expected_roles = set(roles)
        current_roles = set(m.roles)
        if current_roles != expected_roles:
            m.roles = roles
            updated = True

        # Update is_active if different
        if m.is_active != is_active:
            m.is_active = is_active
            updated = True

        if updated:
            m.save(update_fields=["roles", "is_active"])

    return m


def _role_to_roles_array(role: str) -> list[str]:
    """
    Convert single role string to roles array.
    Always includes 'member' as base role.

    Args:
        role: Single role string ('admin', 'steward', 'member')

    Returns:
        List of roles

    Examples:
        'admin' → ['member', 'admin']
        'steward' → ['member', 'steward']
        'member' → ['member']
        'founder' → ['member', 'admin']  # founder treated as admin structurally
    """
    role = role.lower()

    # Founder is treated as admin structurally
    # (will get 'isGroupFounder' decorator in Phase 2)
    if role == "founder":
        return ["member", "admin"]

    if role == "admin":
        return ["member", "admin"]

    if role == "steward":
        return ["member", "steward"]

    # Default: just member
    return ["member"]


def grant_role_to_member(membership, role: str) -> bool:
    """
    Grant an additional role to an existing membership.

    Args:
        membership: GroupMembership instance
        role: Role to grant ('admin', 'steward', etc.)

    Returns:
        True if role was granted, False if already had it
    """
    return membership.grant_role(role)


def revoke_role_from_member(membership, role: str) -> bool:
    """
    Revoke a role from an existing membership.
    Cannot revoke 'member' role.

    Args:
        membership: GroupMembership instance
        role: Role to revoke

    Returns:
        True if role was revoked, False if didn't have it or is 'member'
    """
    if role == "member":
        return False  # Cannot revoke base member role

    return membership.revoke_role(role)


def promote_to_admin(membership) -> bool:
    """
    Promote a member to admin.

    Args:
        membership: GroupMembership instance

    Returns:
        True if promoted, False if already admin
    """
    return membership.grant_role("admin")


def demote_from_admin(membership) -> bool:
    """
    Demote an admin to regular member.
    Removes 'admin' role but keeps 'member'.

    Args:
        membership: GroupMembership instance

    Returns:
        True if demoted, False if wasn't admin
    """
    return membership.revoke_role("admin")
