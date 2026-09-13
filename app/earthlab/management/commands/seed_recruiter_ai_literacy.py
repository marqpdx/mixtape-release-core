"""
Seed the Recruiter AI Literacy pilot course for a group.

Usage:
    python manage.py seed_recruiter_ai_literacy mindful-brilliance
    python manage.py seed_recruiter_ai_literacy mindful-brilliance --username admin
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from groups.models import Group
from orchestration.governed_verbs.adapters import (
    RECRUITER_AI_LITERACY_COURSE_SLUG,
    RECRUITER_AI_LITERACY_LESSONS,
    create_or_update_recruiter_ai_literacy_course,
)


COURSE_SLUG = RECRUITER_AI_LITERACY_COURSE_SLUG


class Command(BaseCommand):
    help = "Seed the Recruiter AI Literacy pilot EarthLab course for a group. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("group_slug", help="Group slug that should sponsor the course.")
        parser.add_argument(
            "--username",
            default="",
            help="Optional author/submitted_by username. Defaults to the first superuser, then first user.",
        )
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Seed course and lessons as draft instead of published.",
        )

    def handle(self, *args, **options):
        group_slug = options["group_slug"]
        group = Group.objects.filter(slug=group_slug).first()
        if not group:
            raise CommandError(f"Group not found: {group_slug}")

        author = self._resolve_author(options["username"])
        result = create_or_update_recruiter_ai_literacy_course(
            group=group,
            author=author,
            draft=options["draft"],
        )

        action = "created" if result.created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Recruiter AI Literacy course {action} for {group.slug}: "
                f"{len(RECRUITER_AI_LITERACY_LESSONS)} lessons, slug={COURSE_SLUG}"
            )
        )

    def _resolve_author(self, username):
        User = get_user_model()
        if username:
            user = User.objects.filter(username=username).first()
            if not user:
                raise CommandError(f"User not found: {username}")
            return user
        return User.objects.filter(is_superuser=True).first() or User.objects.first()
