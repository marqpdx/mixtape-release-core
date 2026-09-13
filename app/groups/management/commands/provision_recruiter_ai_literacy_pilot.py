"""
Provision the Recruiter AI Literacy pilot as ordinary Crossroads primitives.

Usage:
    python manage.py provision_recruiter_ai_literacy_pilot --admin admin
    python manage.py provision_recruiter_ai_literacy_pilot --admin mark --draft-course
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from groups.models import Group, GroupMembership
from groups.models.dec_enums import AdmissionPolicy, GroupType, GroupVisibility
from groups.services.groups import GroupService
from groups.services.permission_profiles import assign_default_permission_profile
from threadworks.models import Discussion, Forum


PILOT_GROUP_SLUG = "recruiter-ai-literacy"
PILOT_GROUP_TITLE = "Recruiter AI Literacy"
PILOT_FORUM_SLUG = "recruiter-ai-literacy"


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

        with transaction.atomic():
            group, group_created = self._provision_group(admin, group_slug)
            membership, membership_created = self._provision_admin_membership(group, admin)
            forum, forum_created = self._provision_forum(group)
            discussions = self._provision_discussions(forum, admin)

        if not options["skip_course"]:
            call_args = [group.slug, "--username", admin.username]
            if options["draft_course"]:
                call_args.append("--draft")
            call_command("seed_recruiter_ai_literacy", *call_args)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Recruiter AI Literacy pilot provisioned."))
        self.stdout.write(f"  group: {group.title} ({group.slug}) {'created' if group_created else 'updated'}")
        self.stdout.write(
            f"  admin: {admin.username} roles={membership.roles} "
            f"{'created' if membership_created else 'updated'}"
        )
        self.stdout.write(f"  forum: {forum.title} ({forum.slug}) {'created' if forum_created else 'updated'}")
        self.stdout.write(f"  discussions: {', '.join(d.title for d in discussions)}")
        self.stdout.write("  course: skipped" if options["skip_course"] else "  course: seeded via EarthLab")

    def _get_admin(self, username):
        User = get_user_model()
        admin = User.objects.filter(username=username).first()
        if not admin:
            raise CommandError(f"User not found: {username}")
        return admin

    def _provision_group(self, admin, group_slug):
        group = Group.objects.filter(slug=group_slug).first()
        if not group:
            group = GroupService.create_group(
                title=PILOT_GROUP_TITLE,
                group_type=GroupType.COMMUNITY,
                created_by=admin,
                description=(
                    "A bounded learning group for recruiters practicing careful investigation "
                    "of unfamiliar technical material with modern language tools."
                ),
                summary=(
                    "A small recruiter-focused Crossroads pilot for AI literacy, technical "
                    "job-description analysis, and human-centered information work."
                ),
                visibility=GroupVisibility.PRIVATE,
                slug=group_slug,
            )
            created = True
        else:
            created = False

        group.title = PILOT_GROUP_TITLE
        group.description = (
            "A bounded learning group for recruiters practicing careful investigation "
            "of unfamiliar technical material with modern language tools."
        )
        group.summary = (
            "A small recruiter-focused Crossroads pilot for AI literacy, technical "
            "job-description analysis, and human-centered information work."
        )
        group.tagline = "Learn to investigate technical work with clarity, caution, and confidence."
        group.group_type = GroupType.COMMUNITY
        group.visibility = GroupVisibility.PRIVATE
        group.admission_policy = AdmissionPolicy.INVITE_ONLY
        group.is_active = True
        group.escrow_owner = group.escrow_owner or admin
        group.save(
            update_fields=[
                "title",
                "description",
                "summary",
                "tagline",
                "group_type",
                "visibility",
                "admission_policy",
                "is_active",
                "escrow_owner",
                "updated_at",
            ]
        )
        return group, created

    def _provision_admin_membership(self, group, admin):
        user_ct = ContentType.objects.get_for_model(admin.__class__)
        membership, created = GroupMembership.objects.get_or_create(
            group=group,
            member_content_type=user_ct,
            member_object_id=admin.pk,
            defaults={
                "roles": ["member", "admin", "owner"],
                "is_active": True,
                "is_pending": False,
            },
        )
        if created:
            assign_default_permission_profile(membership, assigned_by=admin)

        changed = False
        desired_roles = ["member", "admin", "owner"]
        for role in desired_roles:
            if role not in membership.roles:
                membership.roles.append(role)
                changed = True
        if membership.is_pending or not membership.is_active:
            membership.is_pending = False
            membership.is_active = True
            changed = True
        if changed:
            membership.save(update_fields=["roles", "is_pending", "is_active", "updated_at"])
        return membership, created

    def _provision_forum(self, group):
        group_ct = ContentType.objects.get_for_model(group.__class__)
        forum, created = Forum.objects.update_or_create(
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
            slug=PILOT_FORUM_SLUG,
            defaults={
                "title": "Recruiter AI Literacy",
                "slug_is_custom": True,
                "summary": "Questions and reflections for the Recruiter AI Literacy pilot.",
                "description": (
                    "A bounded discussion space for course questions, job-description lab notes, "
                    "and practical reflections from the recruiter AI literacy pilot."
                ),
                "visibility": "group",
                "audience_type": "all_members",
                "auto_add_new_members": True,
                "is_archived": False,
            },
        )
        return forum, created

    def _provision_discussions(self, forum, admin):
        specs = [
            {
                "slug": "introductions-and-questions",
                "title": "Introductions and questions",
                "description": (
                    "Say hello, name the kinds of roles or job descriptions you work with, "
                    "and leave questions as you move through the course."
                ),
                "status": "pinned",
                "pinned_nav_name": "Questions",
            },
            {
                "slug": "job-description-lab-notes",
                "title": "Job-description lab notes",
                "description": (
                    "Use this thread for notes from real technical job descriptions: unclear terms, "
                    "candidate questions, hiring-manager questions, and verification gaps."
                ),
                "status": "active",
                "pinned_nav_name": "",
            },
        ]
        discussions = []
        for spec in specs:
            discussion, _ = Discussion.objects.update_or_create(
                forum=forum,
                slug=spec["slug"],
                defaults={
                    "title": spec["title"],
                    "slug_is_custom": True,
                    "description": spec["description"],
                    "status": spec["status"],
                    "pinned_nav_name": spec["pinned_nav_name"],
                    "visibility_scope": "group",
                    "created_by": admin,
                    "is_locked": False,
                    "is_deleted": False,
                },
            )
            discussions.append(discussion)
        return discussions
