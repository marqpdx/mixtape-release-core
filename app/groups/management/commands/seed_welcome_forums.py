"""
Backfill Welcome Forum + Tell About Yourself discussion for existing groups.

Usage:
    python manage.py seed_welcome_forums [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from groups.models import Group
from groups.signals import _seed_welcome_forum
from threadworks.models import Forum


class Command(BaseCommand):
    help = "Seed a Welcome Forum + Tell About Yourself discussion for groups that don't have one."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report which groups would be seeded without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        group_ct = ContentType.objects.get_for_model(Group)

        # Groups that already have a Welcome forum
        seeded_ids = Forum.objects.filter(
            sponsor_content_type=group_ct,
            title="Welcome",
        ).values_list('sponsor_object_id', flat=True)

        groups_to_seed = Group.objects.exclude(id__in=seeded_ids)
        total = groups_to_seed.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("All groups already have a Welcome forum."))
            return

        self.stdout.write(f"{'[DRY RUN] ' if dry_run else ''}{total} group(s) to seed:")

        seeded = 0
        errors = 0
        for group in groups_to_seed.iterator():
            self.stdout.write(f"  {'would seed' if dry_run else 'seeding'}: {group.title} ({group.slug})")
            if not dry_run:
                try:
                    _seed_welcome_forum(group)
                    seeded += 1
                except Exception as exc:
                    self.stderr.write(f"    ERROR for {group.slug}: {exc}")
                    errors += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Done. Seeded: {seeded}  Errors: {errors}"
            ))
