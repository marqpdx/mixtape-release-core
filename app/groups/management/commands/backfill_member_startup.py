# groups/management/commands/backfill_member_startup.py

"""
One-off backfill: run MemberStartupService for all active users who have an
accepted Crossroads membership. Idempotent — safe to re-run.

Usage:
    python manage.py backfill_member_startup
    python manage.py backfill_member_startup --dry-run
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from groups.models import GroupMembership
from groups.models.group import Group
from groups.services.member_startup import MemberStartupService

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Backfill MemberStartupService for existing members (Personal Initiative + ApertureLog)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be done without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        crossroads_slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "crossroads")

        try:
            crossroads = Group.objects.get(slug=crossroads_slug)
        except Group.DoesNotExist:
            self.stderr.write(f"Crossroads group '{crossroads_slug}' not found. Aborting.")
            return

        user_ct = ContentType.objects.get_for_model(User)
        memberships = GroupMembership.objects.filter(
            group=crossroads,
            member_content_type=user_ct,
            is_active=True,
            is_pending=False,
        ).select_related()

        total = memberships.count()
        self.stdout.write(f"Found {total} active Crossroads members to process.")

        if dry_run:
            self.stdout.write("[DRY RUN] No changes will be made.")
            return

        ok = 0
        errors = 0
        for membership in memberships:
            try:
                user = User.objects.filter(pk=membership.member_object_id).first()
                if user is None:
                    self.stdout.write(f"  ⚠ skipped stale membership {membership.member_object_id} (user not found)")
                    continue
                result = MemberStartupService.run(user=user)
                status_str = "new" if result.was_new else "existing"
                self.stdout.write(f"  ✓ {user.username} ({status_str})")
                ok += 1
            except Exception as exc:
                self.stderr.write(f"  ✗ member_object_id={membership.member_object_id}: {exc}")
                logger.exception("backfill_member_startup error for %s", membership.member_object_id)
                errors += 1

        self.stdout.write(f"\nDone. {ok} processed, {errors} errors.")
