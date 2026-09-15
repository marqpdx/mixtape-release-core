"""
Provision a new tenant Group for the Crossroads platform.

This is the minimum viable provisioning path — no admin UI yet. Creates the
Group record with the correct tenant flags and reports the result. Does not
create memberships, public pages, or Catalyst Codex — those are separate steps.

Usage:
    python manage.py provision_tenant --slug=mindful-brilliance \\
        --title="Mindful Brilliance" \\
        --catalyst-enabled

Options:
    --slug           Group slug (required, must be unique)
    --title          Display title (required)
    --catalyst-enabled     Set catalyst_enabled=True
    --directory      Set in_crossroads_directory=True (default: False; use with care)
    --dry-run        Print what would be created without writing to the database
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from mixtape.tenant_urls import get_catalyst_workspace_url


class Command(BaseCommand):
    help = "Provision a new tenant Group for the Crossroads platform."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True, help="Group slug (unique, URL-safe)")
        parser.add_argument("--title", required=True, help="Display title for the group")
        parser.add_argument(
            "--catalyst-enabled",
            action="store_true",
            default=False,
            help="Enable Catalyst features for this tenant",
        )
        parser.add_argument(
            "--directory",
            action="store_true",
            default=False,
            help="Opt into Crossroads public directory (in_crossroads_directory=True). "
                 "Default is False — standalone tenants should omit this flag.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be created without writing to the database",
        )

    def handle(self, *args, **options):
        from groups.models.group import Group

        slug = options["slug"]
        title = options["title"]
        catalyst_enabled = options["catalyst_enabled"]
        in_crossroads_directory = options["directory"]
        dry_run = options["dry_run"]

        # Validate slug is available
        if Group.objects.filter(slug=slug).exists():
            raise CommandError(f"A Group with slug '{slug}' already exists.")

        self.stdout.write(f"\nTenant provisioning {'(DRY RUN) ' if dry_run else ''}—")
        self.stdout.write(f"  slug:                    {slug}")
        self.stdout.write(f"  title:                   {title}")
        self.stdout.write(f"  catalyst_enabled:        {catalyst_enabled}")
        self.stdout.write(f"  in_crossroads_directory: {in_crossroads_directory}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run — no changes written."))
            return

        with transaction.atomic():
            from django.contrib.contenttypes.models import ContentType
            from groups.models.dec_enums import GroupType, GroupVisibility

            # Tenant groups are self-sponsored at creation (sponsor = self).
            # A placeholder ContentType is needed before the Group exists;
            # we create the group first with a temporary sponsor then update.
            group = Group(
                slug=slug,
                title=title,
                group_type=GroupType.ORGANIZATION,
                visibility=GroupVisibility.PUBLIC,
                is_active=True,
                catalyst_enabled=catalyst_enabled,
                in_crossroads_directory=in_crossroads_directory,
            )

            # Bootstrap sponsor: tenant groups sponsor themselves
            ct = ContentType.objects.get_for_model(Group)
            group.sponsor_content_type = ct
            # We need a UUID before save for the self-reference; uuid4 is already set by default
            group.sponsor_object_id = group.id
            group.save()

        self.stdout.write(self.style.SUCCESS(
            f"\nProvisioned: {group.title} ({group.slug}) — pk={group.pk}"
        ))
        self.stdout.write(
            f"  Subdomain URL: {get_catalyst_workspace_url(slug)}\n"
        )
