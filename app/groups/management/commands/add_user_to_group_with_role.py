# groups/management/commands/add_user_to_group_with_role.py
"""
Add a user to a group with a role, or grant an additional role if already a member.

Usage:
    python manage.py add_user_to_group_with_role <username> <group-slug> <role>

Roles: member, steward, admin, owner
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from groups.models import GroupMembership
from groups.models.group import Group
from groups.services.permission_profiles import assign_default_permission_profile


User = get_user_model()


class Command(BaseCommand):
    help = "Add a user to a group with a role, or grant an additional role if already a member."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Username of the user to add.")
        parser.add_argument("group_slug", help="Slug of the target group.")
        parser.add_argument("role", help="Role to assign (member, steward, admin, owner).")

    def handle(self, *args, **options):
        username = options["username"]
        group_slug = options["group_slug"]
        role = options["role"].lower()

        valid_roles = {"member", "steward", "admin", "owner"}
        if role not in valid_roles:
            raise CommandError(
                f"Invalid role '{role}'. Choose from: {', '.join(sorted(valid_roles))}"
            )

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"No user with username='{username}'")

        try:
            group = Group.objects.get(slug=group_slug)
        except Group.DoesNotExist:
            raise CommandError(f"No group with slug='{group_slug}'")

        user_ct = ContentType.objects.get_for_model(User)

        with transaction.atomic():
            membership, created = GroupMembership.objects.get_or_create(
                group=group,
                member_content_type=user_ct,
                member_object_id=user.pk,
                defaults={"roles": ["member"], "is_active": True},
            )

            if created:
                assign_default_permission_profile(membership, assigned_by=user)

            if role not in membership.roles:
                membership.grant_role(role)
                action = "added to group and granted" if created else "granted"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"User '{username}' {action} role '{role}' in group '{group_slug}'.\n"
                        f"Current roles: {membership.roles}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"User '{username}' already has role '{role}' in group '{group_slug}'. No change.\n"
                        f"Current roles: {membership.roles}"
                    )
                )
