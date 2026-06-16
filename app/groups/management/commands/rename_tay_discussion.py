"""
Rename the legacy "Tell About Yourself" discussion to "Who We Are" on
existing community groups.

Targets any Discussion with slug="tell-about-yourself" inside a forum
titled "Welcome" that is sponsored by a community Group.

Usage:
    python manage.py rename_tay_discussion [--dry-run]
"""

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType

from groups.models import Group
from threadworks.models import Forum, Discussion


class Command(BaseCommand):
    help = 'Rename "Tell About Yourself" discussion to "Who We Are" on community groups.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report which discussions would be updated without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        group_ct = ContentType.objects.get_for_model(Group)

        welcome_forums = Forum.objects.filter(
            sponsor_content_type=group_ct,
            title="Welcome",
        ).select_related()

        targets = Discussion.objects.filter(
            forum__in=welcome_forums,
            slug="tell-about-yourself",
        )

        total = targets.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No legacy discussions found — nothing to do."))
            return

        self.stdout.write(f"{'[DRY RUN] ' if dry_run else ''}{total} discussion(s) to rename:")

        updated = 0
        errors = 0
        for discussion in targets.select_related("forum").iterator():
            group_id = discussion.forum.sponsor_object_id
            self.stdout.write(
                f"  {'would rename' if dry_run else 'renaming'}: "
                f'"{discussion.title}" (group id={group_id})'
            )
            if not dry_run:
                try:
                    group = Group.objects.select_related("escrow_owner").get(id=group_id)
                    discussion.title = "Who We Are"
                    discussion.slug = "who-we-are"
                    discussion.pinned_nav_name = ""
                    discussion.created_by = group.escrow_owner
                    discussion.save(update_fields=["title", "slug", "pinned_nav_name", "created_by"])
                    updated += 1
                except Exception as exc:
                    self.stderr.write(f"    ERROR for discussion id={discussion.id}: {exc}")
                    errors += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"Done. Updated: {updated}  Errors: {errors}"
            ))
