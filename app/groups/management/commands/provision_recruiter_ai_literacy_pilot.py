"""
Provision the Recruiter AI Literacy pilot as ordinary Crossroads primitives.

Usage:
    python manage.py provision_recruiter_ai_literacy_pilot --admin admin
    python manage.py provision_recruiter_ai_literacy_pilot --admin mark --draft-course
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from orchestration.governed_verbs.adapters import (
    RECRUITER_AI_LITERACY_FORUM_SLUG,
    RECRUITER_AI_LITERACY_GROUP_SLUG,
    RECRUITER_AI_LITERACY_GROUP_TITLE,
    provision_recruiter_ai_literacy_install,
)


PILOT_GROUP_SLUG = RECRUITER_AI_LITERACY_GROUP_SLUG
PILOT_GROUP_TITLE = RECRUITER_AI_LITERACY_GROUP_TITLE
PILOT_FORUM_SLUG = RECRUITER_AI_LITERACY_FORUM_SLUG


class Command(BaseCommand):
    help = "Provision the Recruiter AI Literacy pilot group, course, and discussion space. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin",
            default="admin",
            help="Username to make pilot steward/admin. Defaults to admin.",
        )
        parser.add_argument(
            "--group-slug",
            default=PILOT_GROUP_SLUG,
            help=f"Pilot group slug. Defaults to {PILOT_GROUP_SLUG}.",
        )
        parser.add_argument(
            "--draft-course",
            action="store_true",
            help="Seed the EarthLab course as draft instead of published.",
        )
        parser.add_argument(
            "--skip-course",
            action="store_true",
            help="Provision group/discussion only; do not seed EarthLab course.",
        )

    def handle(self, *args, **options):
        admin = self._get_admin(options["admin"])
        group_slug = options["group_slug"]

        result = provision_recruiter_ai_literacy_install(
            admin_username=admin.username,
            group_slug=group_slug,
            draft_course=options["draft_course"],
            skip_course=options["skip_course"],
        )
        group = result["group"].obj
        membership = result["membership"].obj
        forum = result["forum"].obj
        discussion_titles = result["forum"].details["discussion_titles"]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Recruiter AI Literacy pilot provisioned."))
        self.stdout.write(
            f"  group: {group.title} ({group.slug}) "
            f"{'created' if result['group'].created else 'updated'}"
        )
        self.stdout.write(
            f"  admin: {admin.username} roles={membership.roles} "
            f"{'created' if result['membership'].created else 'updated'}"
        )
        self.stdout.write(
            f"  forum: {forum.title} ({forum.slug}) "
            f"{'created' if result['forum'].created else 'updated'}"
        )
        self.stdout.write(f"  discussions: {', '.join(discussion_titles)}")
        self.stdout.write("  course: skipped" if options["skip_course"] else "  course: seeded via EarthLab")

    def _get_admin(self, username):
        User = get_user_model()
        admin = User.objects.filter(username=username).first()
        if not admin:
            raise CommandError(f"User not found: {username}")
        return admin
