# initiatives/management/commands/delete_initiative.py
"""
Delete an Initiative by ID or title substring.

Usage:
    # Preview what would be deleted
    python manage.py delete_initiative --id <uuid> --dry-run
    python manage.py delete_initiative --title "Archetypes" --dry-run

    # Soft delete (sets deleted_at, cascade via app logic)
    python manage.py delete_initiative --id <uuid> --soft

    # Hard delete (removes all rows — use for test data cleanup)
    python manage.py delete_initiative --id <uuid> --hard

    # Hard delete all initiatives for a group
    python manage.py delete_initiative --group <slug> --hard
"""

from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from initiatives.models import ApertureLog, ApertureLogEntry, Initiative


class Command(BaseCommand):
    help = "Delete one or more Initiatives (soft or hard)."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--id", dest="initiative_id", help="UUID of the Initiative to delete.")
        target.add_argument("--title", help="Case-insensitive title substring to match.")
        target.add_argument("--group", dest="group_slug", help="Delete all initiatives for this group slug.")

        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--soft", action="store_true", help="Set deleted_at (soft delete).")
        mode.add_argument("--hard", action="store_true", help="Permanently remove all rows.")

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt.",
        )

    def handle(self, *args, **options):
        qs = Initiative.objects.all()

        if options["initiative_id"]:
            qs = qs.filter(id=options["initiative_id"])
        elif options["title"]:
            qs = qs.filter(title__icontains=options["title"])
        elif options["group_slug"]:
            from django.contrib.contenttypes.models import ContentType
            from groups.models import Group
            try:
                group = Group.objects.get(slug=options["group_slug"])
            except Group.DoesNotExist:
                raise CommandError(f"Group not found: {options['group_slug']}")
            group_ct = ContentType.objects.get_for_model(Group)
            qs = qs.filter(
                sponsor_content_type=group_ct,
                sponsor_object_id=group.id,
            )

        initiatives = list(qs.select_related())

        if not initiatives:
            self.stdout.write("No matching initiatives found.")
            return

        mode = "HARD DELETE" if options["hard"] else "SOFT DELETE"
        self.stdout.write(f"\n{mode} — {len(initiatives)} initiative(s):\n")
        for ini in initiatives:
            entry_count = 0
            try:
                entry_count = ini.aperture_log.entries.count()
            except ApertureLog.DoesNotExist:
                pass
            self.stdout.write(
                f"  [{ini.id}] {ini.title}  (status={ini.status}, entries={entry_count})"
            )

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run — no changes made."))
            return

        if not options["yes"]:
            confirm = input(f"\nProceed with {mode} of {len(initiatives)} initiative(s)? [y/N] ").strip().lower()
            if confirm != "y":
                self.stdout.write("Aborted.")
                return

        with transaction.atomic():
            if options["hard"]:
                for ini in initiatives:
                    ini_id = ini.id
                    ini_title = ini.title
                    ini.delete()
                    self.stdout.write(f"  Hard deleted: [{ini_id}] {ini_title}")
            else:
                now = datetime.now(timezone.utc)
                ids = [ini.id for ini in initiatives]
                Initiative.objects.filter(id__in=ids).update(deleted_at=now)
                self.stdout.write(
                    self.style.SUCCESS(f"  Soft deleted {len(initiatives)} initiative(s) (deleted_at={now.isoformat()})")
                )

        self.stdout.write(self.style.SUCCESS(f"\nDone. {len(initiatives)} initiative(s) {mode.lower()}d."))
