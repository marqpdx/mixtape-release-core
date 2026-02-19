# groups/services/join_service.py

"""
Service functions for user-initiated group joining.
Handles direct join, join requests (applications), and admission status.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from groups.models.dec_enums import AdmissionPolicy
from groups.models.group import Group, GroupInvitation, InvitationKind, InvitationStatus
from groups.models.membership import GroupMembership
from groups.services.memberships import ensure_user_membership
from utils.tasks import send_transactional_email_task


User = get_user_model()


def _get_parent_group(group):
    """
    Return the parent/sponsor group if it exists, else None.
    Uses the polymorphic sponsor GFK on BaseContent.
    """
    group_ct = ContentType.objects.get_for_model(Group)
    if group.sponsor_content_type_id == group_ct.id and group.sponsor_object_id:
        try:
            return Group.objects.get(pk=group.sponsor_object_id, is_active=True)
        except Group.DoesNotExist:
            return None
    return None


def _is_user_member_of(group, user):
    """Check if user is an active member of the given group."""
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.pk,
        is_active=True,
        is_banned=False,
        is_evicted=False,
        is_pending=False,
    ).exists()


def _get_existing_membership(group, user):
    """Return active membership or None."""
    user_ct = ContentType.objects.get_for_model(User)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.pk,
    ).first()


def _get_pending_request(group, user):
    """Return pending join request invitation or None."""
    return GroupInvitation.objects.filter(
        group=group,
        invited_user=user,
        invitation_kind=InvitationKind.REQUEST,
        invitation_status=InvitationStatus.PENDING,
    ).first()


def _get_moderator_emails(group):
    """Return emails of group admins/stewards/owners."""
    user_ct = ContentType.objects.get_for_model(User)
    memberships = GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        roles__overlap=["admin", "steward", "owner"],
        is_active=True,
        is_banned=False,
        is_evicted=False,
    ).select_related("member_content_type")

    emails = []
    for m in memberships:
        member = m.member_object
        if member and member.email:
            emails.append(member.email)
    return sorted(set(emails))


def _send_join_request_email(group, user, invitation):
    """Send email to group moderators about a new join request."""
    recipients = _get_moderator_emails(group)
    if not recipients:
        return

    profile = getattr(user, "profile", None)
    display_name = profile.display_name if profile else user.username
    review_url = f"{settings.FRONTEND_URL}/group/{group.slug}/admin/join-requests"

    context = {
        "group_title": group.title,
        "applicant_name": display_name,
        "applicant_username": user.username,
        "message": invitation.message or "",
        "review_url": review_url,
    }

    send_transactional_email_task.delay(
        subject=f"Join request: {display_name} wants to join {group.title}",
        to_emails=recipients,
        template_base="email/join_request",
        context=context,
        invitation_id=invitation.id,
    )


def join_group(group, user):
    """
    User directly joins a group (for OPEN / OPEN_PARENT_MEMBERS policies).

    Validates:
    - Group admission_policy allows direct join
    - If OPEN_PARENT_MEMBERS: user must be active member of parent group
    - User not already a member

    Returns: GroupMembership
    Raises: ValidationError
    """
    policy = group.admission_policy

    if policy not in (AdmissionPolicy.OPEN, AdmissionPolicy.OPEN_PARENT_MEMBERS):
        raise ValidationError("This group does not allow direct joining.")

    # Check existing membership
    existing = _get_existing_membership(group, user)
    if existing and existing.is_active and not existing.is_banned and not existing.is_evicted:
        raise ValidationError("You are already a member of this group.")

    # Parent membership check
    if policy == AdmissionPolicy.OPEN_PARENT_MEMBERS:
        parent = _get_parent_group(group)
        if not parent:
            raise ValidationError("This group requires parent group membership but has no parent group.")
        if not _is_user_member_of(parent, user):
            raise ValidationError(
                f"You must be a member of {parent.title} to join this group."
            )

    membership = ensure_user_membership(group, user, role="member")

    from groups.producers import on_member_joined
    on_member_joined(user=user, group=group, membership=membership)

    return membership


def request_to_join_group(group, user, message=""):
    """
    User submits a join request (for APPLICATION / APPLICATION_PARENT_MEMBERS policies).

    Validates:
    - Group admission_policy allows applications
    - If APPLICATION_PARENT_MEMBERS: user must be active member of parent group
    - No existing pending request
    - User not already a member

    Creates GroupInvitation with kind=REQUEST.
    Returns: GroupInvitation
    Raises: ValidationError
    """
    policy = group.admission_policy

    if policy not in (AdmissionPolicy.APPLICATION, AdmissionPolicy.APPLICATION_PARENT_MEMBERS):
        raise ValidationError("This group does not accept join requests.")

    # Check existing membership
    existing = _get_existing_membership(group, user)
    if existing and existing.is_active and not existing.is_banned and not existing.is_evicted:
        raise ValidationError("You are already a member of this group.")

    # Parent membership check
    if policy == AdmissionPolicy.APPLICATION_PARENT_MEMBERS:
        parent = _get_parent_group(group)
        if not parent:
            raise ValidationError("This group requires parent group membership but has no parent group.")
        if not _is_user_member_of(parent, user):
            raise ValidationError(
                f"You must be a member of {parent.title} to request to join this group."
            )

    # Check for existing pending request
    pending = _get_pending_request(group, user)
    if pending:
        raise ValidationError("You already have a pending join request for this group.")

    invitation = GroupInvitation.objects.create(
        group=group,
        invited_user=user,
        invited_by=user,
        invitation_kind=InvitationKind.REQUEST,
        invitation_status=InvitationStatus.PENDING,
        message=message,
    )

    from groups.producers import on_join_request_submitted
    on_join_request_submitted(user=user, group=group, invitation=invitation)
    _send_join_request_email(group, user, invitation)

    return invitation


def respond_to_join_request(invitation, responder, action):
    """
    Admin/steward accepts or declines a user's join request.

    Args:
        invitation: GroupInvitation with kind=REQUEST
        responder: User performing the action (must be admin/steward)
        action: "accept" or "decline"

    On accept: creates membership via ensure_user_membership().
    On decline: sets invitation_status=DECLINED.

    Returns: GroupMembership | None
    Raises: ValidationError
    """
    if invitation.invitation_kind != InvitationKind.REQUEST:
        raise ValidationError("This is not a join request.")

    if invitation.invitation_status != InvitationStatus.PENDING:
        raise ValidationError("This request has already been processed.")

    from groups.producers import on_join_request_responded

    if action == "accept":
        invitation.invitation_status = InvitationStatus.JOINED
        invitation.save(update_fields=["invitation_status"])
        membership = ensure_user_membership(invitation.group, invitation.invited_user, role="member")
        on_join_request_responded(
            responder=responder, user=invitation.invited_user,
            group=invitation.group, invitation=invitation, action="accept",
        )
        return membership

    elif action == "decline":
        invitation.invitation_status = InvitationStatus.DECLINED
        invitation.save(update_fields=["invitation_status"])
        on_join_request_responded(
            responder=responder, user=invitation.invited_user,
            group=invitation.group, invitation=invitation, action="decline",
        )
        return None

    else:
        raise ValidationError("Action must be 'accept' or 'decline'.")


def get_admission_status(group, user=None):
    """
    Returns the current admission state for a user + group pair.

    Returns dict:
    {
        "policy": str,
        "can_join": bool,
        "can_request": bool,
        "is_member": bool,
        "has_pending_request": bool,
        "parent_group": {"title": str, "slug": str} | None,
        "requires_parent_membership": bool,
        "is_parent_member": bool,
    }
    """
    policy = group.admission_policy
    parent = _get_parent_group(group)
    requires_parent = policy in (
        AdmissionPolicy.OPEN_PARENT_MEMBERS,
        AdmissionPolicy.APPLICATION_PARENT_MEMBERS,
    )

    result = {
        "policy": policy,
        "can_join": False,
        "can_request": False,
        "is_member": False,
        "is_moderator": False,
        "has_pending_request": False,
        "parent_group": {"title": parent.title, "slug": parent.slug} if parent else None,
        "requires_parent_membership": requires_parent,
        "is_parent_member": False,
    }

    if not user or not user.is_authenticated:
        # Anonymous: show policy info only, no action possible
        if policy in (AdmissionPolicy.OPEN, AdmissionPolicy.OPEN_PARENT_MEMBERS):
            result["can_join"] = True  # They'd need to log in first
        elif policy in (AdmissionPolicy.APPLICATION, AdmissionPolicy.APPLICATION_PARENT_MEMBERS):
            result["can_request"] = True
        return result

    # Authenticated user
    is_member = _is_user_member_of(group, user)
    result["is_member"] = is_member

    if is_member:
        # Check if user is admin/steward/owner
        user_ct = ContentType.objects.get_for_model(User)
        membership = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            member_object_id=user.pk,
            is_active=True,
        ).first()
        if membership and (membership.is_admin() or membership.is_steward() or membership.is_owner()):
            result["is_moderator"] = True
        return result

    is_parent_member = _is_user_member_of(parent, user) if parent else False
    result["is_parent_member"] = is_parent_member

    has_pending = _get_pending_request(group, user) is not None
    result["has_pending_request"] = has_pending

    if has_pending:
        return result

    if policy == AdmissionPolicy.OPEN:
        result["can_join"] = True
    elif policy == AdmissionPolicy.OPEN_PARENT_MEMBERS:
        result["can_join"] = is_parent_member
    elif policy == AdmissionPolicy.APPLICATION:
        result["can_request"] = True
    elif policy == AdmissionPolicy.APPLICATION_PARENT_MEMBERS:
        result["can_request"] = is_parent_member
    # INVITE_ONLY and CLOSED: both remain False

    return result
