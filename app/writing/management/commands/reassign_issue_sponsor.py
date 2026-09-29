from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from groups.models import Group
from writing.models import Issue


class Command(BaseCommand):
    help = "Move a member-sponsored Issue to a group after checking every placed piece's sponsor."

    def add_arguments(self, parser):
        parser.add_argument("--issue-id", required=True)
        parser.add_argument("--from-member", required=True)
        parser.add_argument("--group-slug", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options["from_member"]).first()
        group = Group.objects.filter(slug=options["group_slug"]).first()
        if not user or not group:
            raise CommandError("Source member or target group not found.")

        user_ct = ContentType.objects.get_for_model(user)
        group_ct = ContentType.objects.get_for_model(Group)
        with transaction.atomic():
            issue = Issue.objects.select_for_update().filter(pk=options["issue_id"]).first()
            if not issue:
                raise CommandError("Issue not found.")
            if (issue.sponsor_content_type_id != user_ct.pk
                    or issue.sponsor_object_id != user.pk):
                raise CommandError("Issue is not sponsored by the specified member.")

            incompatible = list(
                issue.placements.select_related("piece")
                .exclude(piece__sponsor_content_type=group_ct, piece__sponsor_object_id=group.pk)
                .values_list("piece_id", flat=True)
            )
            if incompatible:
                raise CommandError(
                    f"Issue has {len(incompatible)} piece(s) not sponsored by the target group."
                )

            action = "Moving" if options["execute"] else "Would move"
            self.stdout.write(
                f"{action} Issue {issue.pk} ({issue.title}) from {user.username} "
                f"to {group.slug}; {issue.placements.count()} placed piece(s)."
            )
            if options["execute"]:
                issue.sponsor_content_type = group_ct
                issue.sponsor_object_id = group.pk
                issue.save(update_fields=["sponsor_content_type", "sponsor_object_id", "updated_at"])
                self.stdout.write(self.style.SUCCESS("Issue sponsor updated."))
            else:
                self.stdout.write("Dry run only. Re-run with --execute to apply.")
