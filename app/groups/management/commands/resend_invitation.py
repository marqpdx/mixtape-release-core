# groups/management/commands/resend_invitation.py

"""
Management command to resend a group invitation email.

Usage:
    python manage.py resend_invitation --invitation-id <id>
    python manage.py resend_invitation --email <email@example.com> --group <slug>
    python manage.py resend_invitation --email <email@example.com> --group <slug> --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Resend a pending group invitation email via the Mailjet HTTP API task."

    def add_arguments(self, parser):
        parser.add_argument(
            "--invitation-id",
            type=int,
            dest="invitation_id",
            help="Primary key of the GroupInvitation to resend.",
        )
        parser.add_argument(
            "--email",
            dest="email",
            help="Invited email address (use with --group).",
        )
        parser.add_argument(
            "--group",
            dest="group_slug",
            help="Group slug (use with --email).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Print what would be sent without actually sending.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            dest="force",
            help="Resend even if invitation is not in pending status.",
        )

    def handle(self, *args, **options):
        from groups.models import GroupInvitation
        from groups.models.group import Group, InvitationStatus
        from groups.tasks import send_invitation_email

        invitation = None

        if options["invitation_id"]:
            try:
                invitation = GroupInvitation.objects.select_related(
                    "group", "invited_by", "invited_user"
                ).get(id=options["invitation_id"])
            except GroupInvitation.DoesNotExist:
                raise CommandError(f"No GroupInvitation with id={options['invitation_id']}")

        elif options["email"] and options["group_slug"]:
            try:
                group = Group.objects.get(slug=options["group_slug"])
            except Group.DoesNotExist:
                raise CommandError(f"No group with slug='{options['group_slug']}'")

            invitation = (
                GroupInvitation.objects.select_related("group", "invited_by", "invited_user")
                .filter(group=group, invited_email=options["email"])
                .order_by("-created_at")
                .first()
            )
            if not invitation:
                raise CommandError(
                    f"No invitation found for {options['email']} in group '{options['group_slug']}'"
                )
        else:
            raise CommandError("Provide --invitation-id, or both --email and --group.")

        # Status check
        if invitation.invitation_status != InvitationStatus.PENDING and not options["force"]:
            raise CommandError(
                f"Invitation {invitation.id} has status '{invitation.invitation_status}'. "
                "Use --force to resend anyway."
            )

        self.stdout.write(
            f"Invitation   : {invitation.id}\n"
            f"Email        : {invitation.invited_email}\n"
            f"Group        : {invitation.group.title} ({invitation.group.slug})\n"
            f"Status       : {invitation.invitation_status}\n"
            f"Email status : {invitation.email_status}\n"
            f"Last error   : {invitation.last_send_error or '—'}\n"
            f"Last sent at : {invitation.sent_at or '—'}\n"
            f"Message ID   : {invitation.provider_message_id or '—'}\n"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no email sent."))
            return

        # Regenerate invite_url from the most recent InviteLink for this invitation
        from django.conf import settings
        from groups.models.group import InviteLink

        invite_link = (
            InviteLink.objects.filter(
                user=invitation.invited_user,
                group=invitation.group,
            )
            .order_by("-id")
            .first()
        )

        if invite_link:
            is_existing_user = invitation.invited_user.is_active if invitation.invited_user else False
            if is_existing_user:
                invitation.invite_url = (
                    f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}"
                )
            else:
                invitation.invite_url = (
                    f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}/new"
                )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No InviteLink found for this invitation — invite_url will be empty in the email."
                )
            )

        # Reset email_status so the task starts clean
        invitation.email_status = "sending"
        invitation.save(update_fields=["email_status"])

        result = send_invitation_email.apply_async(
            kwargs={"invitation_id": invitation.id},
        )

        invitation.last_task_id = result.id
        invitation.last_queued_at = timezone.now()
        invitation.save(update_fields=["last_task_id", "last_queued_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Queued send_invitation_email task={result.id} for invitation {invitation.id}"
            )
        )
