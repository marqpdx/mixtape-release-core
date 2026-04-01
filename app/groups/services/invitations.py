# groups/services/invitations.py

"""
Service layer for Group invitation operations.

Phase 2: Core invitation functionality without Activity system.
Activity notifications will be added in a future phase.
"""

import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone as dj_timezone

from groups.models import GroupInvitation, GroupMembership
from groups.models.group import Group, InvitationKind, InvitationStatus, InviteLink
from groups.permissions import canUserModerateGroupUser
from profiles.models import UserProfile
from users.models import Role
from utils.email.shortcode import generate_shortcode
from utils.tasks import send_transactional_email_task  # kept for non-invitation transactional mail


# from invitations.models import InviteLink
# from invitations.utils import generate_shortcode


class InvitationService:
    """Service for handling group invitations."""

    @staticmethod
    def create_invitation(group, user, email, invited_by, message=""):
        """
        Create an invitation for a user to join a group.
        This is your vetted, working code moved to service layer.

        Args:
            group: Group instance
            user: User instance (may be inactive placeholder)
            email: Email address
            invited_by: User sending the invitation
            message: Optional invitation message

        Returns:
            tuple: (invitation, is_existing_user)

        Raises:
            ValidationError: If user is already a member or has pending invitation
        """
        # Check if user is already a member
        user_content_type = ContentType.objects.get_for_model(user)
        existing_membership = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True
        ).first()

        if existing_membership:
            raise ValidationError(f"User {user.username} is already a member of this group")

        # Determine invitation type based on user status
        is_existing_user = user.is_active

        # If a pending invitation already exists, resend it rather than blocking.
        pending_invitation = GroupInvitation.objects.filter(
            group=group,
            invited_email=email,
            invitation_status="pending"
        ).select_related().first()

        if pending_invitation:
            invite_link = InviteLink.objects.filter(
                user=pending_invitation.invited_user,
                group=group,
            ).order_by("-id").first()

            if invite_link:
                if is_existing_user:
                    pending_invitation.invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}"
                else:
                    pending_invitation.invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}/new"
            else:
                # No invite link found — create a fresh one
                token = default_token_generator.make_token(user)
                invite_link = InviteLink.objects.create(
                    user=user,
                    group=group,
                    token=token,
                    shortcode=generate_shortcode(),
                )
                if is_existing_user:
                    pending_invitation.invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}"
                else:
                    pending_invitation.invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}/new"

            pending_invitation.invited_by = invited_by
            pending_invitation.message = message
            pending_invitation.email_status = "sending"
            pending_invitation.save()
            return pending_invitation, is_existing_user

        # Create token and invite link
        token = default_token_generator.make_token(user)
        invite_link = InviteLink.objects.create(
            user=user,
            group=group,
            token=token,
            shortcode=generate_shortcode(),
        )

        # Create invitation
        invitation = GroupInvitation.objects.create(
            group=group,
            invited_email=email,
            invited_by=invited_by,
            message=message,
            invited_user=user,
        )

        # Different URLs for different flows
        if is_existing_user:
            invitation.invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}"
        else:
            invitation.invite_url = f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}/new"

        invitation.save()

        return invitation, is_existing_user


    @staticmethod
    def accept_invitation(invitation, user):
        """
        Accept a group invitation and create membership.

        Args:
            invitation: GroupInvitation instance
            user: User accepting the invitation

        Returns:
            GroupMembership instance

        Raises:
            ValidationError: If invitation is invalid or expired
        """
        from groups.services.memberships import ensure_user_membership

        if invitation.invitation_status != "pending":
            raise ValidationError("This invitation has already been used or cancelled")

        # Create membership with member role
        membership = ensure_user_membership(
            group=invitation.group,
            user=user,
            role="member",
            is_active=True
        )

        # Mark invitation as accepted
        invitation.invitation_status = InvitationStatus.JOINED
        invitation.save()

        return membership


    @staticmethod
    def send_batch_invitations(invitations_data, group, invited_by, message):
        """
        Enqueue invitation emails via the dedicated send_invitation_email Celery task.

        Each invitation is sent through the Mailjet HTTP API (not SMTP) so we get
        a real provider_message_id back and can observe delivery state per invitation.

        Args:
            invitations_data: List of tuples (invitation, is_existing_user)
            group: Group instance (unused here but kept for API consistency)
            invited_by: User who sent the invitation (unused here but kept for API consistency)
            message: Optional personal message (unused here but kept for API consistency)
        """
        import traceback

        from groups.tasks import send_invitation_email

        for invitation, _is_existing_user in invitations_data:
            try:
                result = send_invitation_email.apply_async(
                    kwargs={"invitation_id": invitation.id},
                )
                invitation.last_task_id = result.id
                invitation.last_queued_at = dj_timezone.now()
                invitation.save(update_fields=["last_task_id", "last_queued_at"])

                print(
                    f"[{dj_timezone.now().isoformat()}] [invite-service] queued"
                    f" invitation={invitation.id} email={invitation.invited_email}"
                    f" task={result.id}"
                )

            except Exception as e:
                print(f"[ERROR] send_batch_invitations failed for {invitation.invited_email}: {e}")
                traceback.print_exc()
                raise


    @staticmethod
    def accept_invite_by_shortcode(shortcode, password=None, username=None, authenticated_user=None):
        """
        Process invitation acceptance by shortcode.
        Handles both new users (activation) and existing users (join group).

        Args:
            shortcode: InviteLink shortcode
            password: Password for new user activation (required if new user)
            username: Username for new user activation (required if new user)
            authenticated_user: Currently authenticated user (for existing user flow)

        Returns:
            dict: {
                'success': bool,
                'user': User instance,
                'group': Group instance,
                'membership': GroupMembership instance,
                'user_was_new': bool
            }

        Raises:
            ValidationError: With specific error message for various failure cases
        """

        User = get_user_model()

        # Lookup the InviteLink
        try:
            invite = InviteLink.objects.get(shortcode=shortcode)
        except InviteLink.DoesNotExist:
            raise ValidationError("Invalid or expired invite link.")

        user = invite.user
        group = invite.group
        token = invite.token

        # Check if invite already used
        if invite.is_used:
            raise ValidationError("This invitation has already been used.")

        # Verify token validity
        if not default_token_generator.check_token(user, token):
            raise ValidationError("Invalid or expired token.")

        user_was_new = False

        # BRANCH: New user (ghost) vs Existing user
        if not user.is_active:
            # NEW USER FLOW: Activate ghost account
            user_was_new = True

            if not all([password, username]):
                raise ValidationError("Username and password required for new accounts.")

            if not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
                raise ValidationError("Invalid username format.")

            if User.objects.filter(username=username).exists():
                raise ValidationError("Username already taken.")

            # Activate the user
            user.username = username
            user.set_password(password)
            user.is_active = True

            # Assign member role
            member_role, _ = Role.objects.get_or_create(name="member")
            user.roles.add(member_role)
            user.save()

            # Create user profile
            UserProfile.objects.get_or_create(
                user=user,
                defaults={"display_name": username}
            )

        else:
            # EXISTING USER FLOW: Verify authenticated user
            if not authenticated_user or not authenticated_user.is_authenticated:
                raise ValidationError("Authentication required. Please log in first.")

            # Verify the invite is for the logged-in user
            if authenticated_user.id != user.id:
                raise ValidationError("This invitation is for a different user.")

        # COMMON: Create group membership (for both new and existing users)
        user_ct = ContentType.objects.get_for_model(User)

        # Get the invitation record
        invitation = GroupInvitation.objects.filter(
            invited_user=user,
            group=group,
            invitation_status="pending"
        ).first()

        if not invitation:
            raise ValidationError("No pending invitation found.")

        # Create or update membership with new roles system
        membership, created = GroupMembership.objects.get_or_create(
            member_content_type=user_ct,
            member_object_id=user.id,
            group=group,
            defaults={
                "roles": ["member"],  # New: use roles array
                "is_active": True,
                "is_pending": False,
                "invited_by": invitation.invited_by,
            }
        )

        if not created:
            # Reactivate if previously existed
            membership.is_active = True
            membership.is_pending = False
            if "member" not in membership.roles:
                membership.roles.append("member")
            membership.save()

        # Update invitation status
        invitation.invitation_status = "joined"
        invitation.save()

        # Mark invite link as used
        invite.is_used = True
        invite.save()

        return {
            "success": True,
            "user": user,
            "group": group,
            "membership": membership,
            "user_was_new": user_was_new
        }


    @staticmethod
    def create_group_invitation(coalition, invited_group, invited_by, message="", kind=InvitationKind.INVITE):
        """
        Create a group-to-group invitation or join request.
        """
        if invited_group.pk == coalition.pk:
            raise ValidationError("A group cannot invite itself.")

        group_ct = ContentType.objects.get_for_model(Group)
        existing_membership = GroupMembership.objects.filter(
            group=coalition,
            member_content_type=group_ct,
            member_object_id=invited_group.pk,
            is_active=True,
            is_banned=False,
            is_evicted=False,
        ).first()

        if existing_membership:
            raise ValidationError(f"{invited_group.title} is already a member of {coalition.title}.")

        pending_invitation = GroupInvitation.objects.filter(
            group=coalition,
            invited_group=invited_group,
            invitation_status=InvitationStatus.PENDING,
        ).first()

        if pending_invitation:
            raise ValidationError(f"A pending invitation already exists for {invited_group.title}.")

        invitation = GroupInvitation.objects.create(
            group=coalition,
            invited_group=invited_group,
            invited_by=invited_by,
            message=message,
            invitation_kind=kind,
        )

        InvitationService.send_group_invitation_email(invitation)

        return invitation


    @staticmethod
    def respond_to_group_invitation(invitation, user, action):
        """
        Accept or decline a group invitation/request.
        """
        if invitation.invitation_status != InvitationStatus.PENDING:
            raise ValidationError("This invitation has already been used or cancelled.")

        if not invitation.invited_group:
            raise ValidationError("This invitation is not for a group.")

        coalition = invitation.group
        invited_group = invitation.invited_group

        can_moderate_coalition = canUserModerateGroupUser(user, coalition)
        can_moderate_invited_group = canUserModerateGroupUser(user, invited_group)

        if invitation.invitation_kind == InvitationKind.INVITE and not can_moderate_invited_group:
            raise ValidationError("You do not have permission to accept this invitation.")

        if invitation.invitation_kind == InvitationKind.REQUEST and not can_moderate_coalition:
            raise ValidationError("You do not have permission to approve this request.")

        if action == "decline":
            invitation.invitation_status = InvitationStatus.DECLINED
            invitation.save(update_fields=["invitation_status"])
            return None

        if action != "accept":
            raise ValidationError("Invalid action.")

        from groups.services.memberships import ensure_group_membership

        membership = ensure_group_membership(
            group=coalition,
            member_group=invited_group,
            role="member",
            is_active=True,
            is_pending=False,
        )

        invitation.invitation_status = InvitationStatus.JOINED
        invitation.save(update_fields=["invitation_status"])

        return membership

    @staticmethod
    def send_group_invitation_email(invitation: GroupInvitation) -> None:
        """
        Send coalition invitation/request emails to group moderators.
        """
        if not invitation.invited_group:
            return

        recipients = InvitationService._get_group_moderator_emails(
            invitation.group if invitation.invitation_kind == InvitationKind.REQUEST else invitation.invited_group
        )
        if not recipients:
            return

        inviter_name = invitation.invited_by.get_full_name() if invitation.invited_by else ""
        coalition = invitation.group
        invited_group = invitation.invited_group

        if invitation.invitation_kind == InvitationKind.REQUEST:
            subject = f"Join request: {invited_group.title} → {coalition.title}"
            headline = f"{invited_group.title} wants to join {coalition.title}"
            cta_label = "Review request"
            target_group_slug = coalition.slug
        else:
            subject = f"Coalition invite: {coalition.title}"
            headline = f"{coalition.title} invited {invited_group.title}"
            cta_label = "Review invite"
            target_group_slug = invited_group.slug

        invite_url = f"{settings.FRONTEND_URL}/groups/{target_group_slug}?view=admin&section=coalition-invitations"

        context = {
            "headline": headline,
            "invited_by_name": inviter_name,
            "coalition_name": coalition.title,
            "group_name": invited_group.title,
            "message": invitation.message,
            "invite_url": invite_url,
            "cta_label": cta_label,
        }

        send_transactional_email_task.delay(
            subject=subject,
            to_emails=recipients,
            template_base="email/invite_group_to_coalition",
            context=context,
            invitation_id=invitation.id,
        )

    @staticmethod
    def _get_group_moderator_emails(group: Group) -> list[str]:
        """
        Return unique emails for admin/steward members of a group.
        """
        user_ct = ContentType.objects.get_for_model(get_user_model())
        memberships = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            roles__overlap=["admin", "steward"],
            is_active=True,
            is_banned=False,
            is_evicted=False,
        ).select_related("member_content_type")

        emails = []
        for membership in memberships:
            user = membership.member_object
            if user and user.email:
                emails.append(user.email)

        return sorted(set(emails))
