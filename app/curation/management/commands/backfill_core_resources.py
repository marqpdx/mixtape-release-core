# curation/management/commands/backfill_core_resources.py

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType


class Command(BaseCommand):
    help = "Create a 'Core Resources' collection for any group that doesn't already have one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        from groups.models import Group
        from curation.models import Collection

        dry_run = options["dry_run"]
        group_ct = ContentType.objects.get_for_model(Group)

        groups = Group.objects.filter(deleted_at__isnull=True, is_active=True)
        created_count = 0
        skipped_count = 0

        for group in groups:
            already = Collection.objects.filter(
                title="Core Resources",
                sponsor_content_type=group_ct,
                sponsor_object_id=group.id,
            ).exists()

            if already:
                skipped_count += 1
                continue

            if dry_run:
                self.stdout.write(f"  [dry-run] would create Core Resources for: {group.title} ({group.id})")
            else:
                Collection.objects.create(
                    title="Core Resources",
                    sponsor_content_type=group_ct,
                    sponsor_object_id=group.id,
                    visibility="members",
                    scope="general",
                )
            created_count += 1

        label = "Would create" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{label} {created_count} Core Resources collections. "
                f"Skipped {skipped_count} groups that already had one."
            )
        )
