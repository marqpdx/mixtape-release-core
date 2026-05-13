# groups/management/commands/resend_invite.py
"""
Resend a pending group invitation by invited email address.

If the email has invitations in multiple groups, lists them and requires --group.

Usage:
    python manage.py resend_invite <email>
    python manage.py resend_invite <email> --group <slug>
    python manage.py resend_invite <email> --group <slug> --force
    python manage.py resend_invite <email> --group <slug> --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Resend a pending group invitation by invited email address."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email address of the invited person.")
        parser.add_argument(
            "--group",
            dest="group_slug",
            help="Group slug (required if email has invitations in multiple groups).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Resend even if invitation is not in pending status.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Print what would be sent without actually sending.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        from groups.models import GroupInvitation
        from groups.models.group import Group, InvitationStatus, InviteLink
        from groups.tasks import send_invitation_email

        email = options["email"]
        group_slug = options["group_slug"]

        qs = GroupInvitation.objects.select_related(
            "group", "invited_by", "invited_user"
        ).filter(invited_email=email).order_by("-created_at")

        if group_slug:
            try:
                group = Group.objects.get(slug=group_slug)
            except Group.DoesNotExist:
                raise CommandError(f"No group with slug='{group_slug}'")
            qs = qs.filter(group=group)

        invitations = list(qs)

        if not invitations:
            msg = f"No invitation found for '{email}'"
            if group_slug:
                msg += f" in group '{group_slug}'"
            raise CommandError(msg)

        if len(invitations) > 1 and not group_slug:
            groups_list = "\n".join(
                f"  {i.group.slug} — {i.group.title} (status: {i.invitation_status})"
                for i in invitations
            )
            raise CommandError(
                f"'{email}' has invitations in multiple groups. Use --group <slug>:\n{groups_list}"
            )

        invitation = invitations[0]

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
        )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — no email sent."))
            return

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
            suffix = "" if is_existing_user else "/new"
            invitation.invite_url = (
                f"{settings.FRONTEND_URL}/app/invitations/accept/{invite_link.shortcode}{suffix}"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No InviteLink found — invite_url will be empty in the email."
                )
            )

        invitation.email_status = "sending"
        invitation.save(update_fields=["email_status"])

        result = send_invitation_email.apply_async(kwargs={"invitation_id": invitation.id})

        invitation.last_task_id = result.id
        invitation.last_queued_at = timezone.now()
        invitation.save(update_fields=["last_task_id", "last_queued_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Queued send_invitation_email task={result.id} for invitation {invitation.id}"
            )
        )
