# groups/services/invitations.py

"""
Service layer for Group invitation operations.
"""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from activity.models import Action, ActionOutbox, ActivityType
from activity.tasks import fanout_action_task
from groups.models import Group, GroupMembership, GroupInvitation
from groups.models.group import InviteLink
from profiles.models import UserProfile
from utils.email.shortcode import generate_shortcode

from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import get_user_model
from users.models import Role
import re

from utils.tasks import send_transactional_email_task


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

        # Check for pending invitation
        pending_invitation = GroupInvitation.objects.filter(
            group=group,
            invited_email=email,
            invitation_status='pending'
        ).first()

        if pending_invitation:
            raise ValidationError(f"An invitation is already pending for {email}")

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
            invitation.invite_url = f"{settings.FRONTEND_URL}/invitations/accept/{invite_link.shortcode}"
        else:
            invitation.invite_url = f"{settings.FRONTEND_URL}/invitations/accept/{invite_link.shortcode}/new"

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

        if invitation.invitation_status != 'pending':
            raise ValidationError("This invitation has already been used or cancelled")

        # Create membership with member role
        membership = ensure_user_membership(
            group=invitation.group,
            user=user,
            role='member',
            is_active=True
        )

        # Mark invitation as accepted
        invitation.invitation_status = 'accepted'
        invitation.save()

        return membership


    @staticmethod
    def send_batch_invitations(invitations_data, group, invited_by, message):
        """Send all invitations via single Celery task"""

        import traceback

        for invitation, is_existing_user in invitations_data:
            try:
                context = {
                    "group_name": group.title,
                    "invited_by_name": invited_by.get_full_name() if invited_by else "",
                    "message": message,
                    "invite_url": invitation.invite_url,
                    "is_existing_user": is_existing_user,
                }

                template = "email/invite_to_group"

                print(f"[DEBUG] About to call send_transactional_email_task")
                print(f"[DEBUG] send_transactional_email_task type: {type(send_transactional_email_task)}")
                print(f"[DEBUG] send_transactional_email_task: {send_transactional_email_task}")

                # Send email via Celery
                send_transactional_email_task.delay(
                    subject=f"You're invited to join {group.title}",
                    to_emails=[invitation.invited_email],
                    template_base=template,
                    context=context,
                    invitation_id=invitation.id,
                )

                print(f"[DEBUG] Email task queued for {invitation.invited_email}")

                # Create in-app notification for existing users
                if is_existing_user:
                    try:
                        activity_type, _ = ActivityType.objects.get_or_create(
                            code="group_invitation",
                            defaults={
                                "title": "Group Invitation",
                                "summary": "Invited to join a group",
                                "default_channel": "activity",
                                "default_priority": "normal",
                            }
                        )

                        group_ct = ContentType.objects.get_for_model(group)
                        action = Action.objects.create(
                            actor_content_type=ContentType.objects.get_for_model(invited_by),
                            actor_id=str(invited_by.id),
                            actor_label="user",
                            object_content_type=group_ct,
                            object_id=str(group.id),
                            verb="invited",
                            activity_type=activity_type,
                            activity_code="group_invitation",
                            channel="activity",
                            priority="normal",
                            metadata={"invite_url": invitation.invite_url},
                            audience={"type": "user", "ids": [str(invitation.invited_user.id)]},
                            dedupe_key=f"group_invite:{group.id}:{invitation.invited_user.id}",
                            aggregate_key=f"group_invites:{group.id}",
                        )

                        print(f"✅ Action created: {action.id}")

                        outbox = ActionOutbox.objects.create(action=action)
                        print(f"📬 Calling fanout_action_task for action {action.id}")

                        print(f"[DEBUG] fanout_action_task type: {type(fanout_action_task)}")
                        print(f"[DEBUG] fanout_action_task: {fanout_action_task}")

                        fanout_action_task.delay(str(action.id))

                    except Exception as e:
                        print(f"[ERROR] Failed to create in-app notification: {e}")
                        traceback.print_exc()

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
                "roles": ['member'],  # New: use roles array
                "is_active": True,
                "is_pending": False,
                "invited_by": invitation.invited_by,
            }
        )

        if not created:
            # Reactivate if previously existed
            membership.is_active = True
            membership.is_pending = False
            if 'member' not in membership.roles:
                membership.roles.append('member')
            membership.save()

        # Update invitation status
        invitation.invitation_status = "joined"
        invitation.save()

        # Mark invite link as used
        invite.is_used = True
        invite.save()

        return {
            'success': True,
            'user': user,
            'group': group,
            'membership': membership,
            'user_was_new': user_was_new
        }



