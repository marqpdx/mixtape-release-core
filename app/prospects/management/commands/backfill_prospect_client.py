# prospects/management/commands/backfill_prospect_client.py
"""
Backfill business.Client records for prospects that were converted before
the Client model existed.

Usage:
    python manage.py backfill_prospect_client
    python manage.py backfill_prospect_client --dry-run
    python manage.py backfill_prospect_client --prospect-slug acme-co
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from business.models import Client
from prospects.models import BusinessProspect

User = get_user_model()


class Command(BaseCommand):
    help = "Create business.Client records for already-converted prospects."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )
        parser.add_argument(
            "--prospect-slug",
            type=str,
            default=None,
            help="Limit to a single prospect by slug.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target_slug = options["prospect_slug"]

        qs = BusinessProspect.objects.filter(
            converted_to_group__isnull=False,
        ).select_related("converted_to_group")

        if target_slug:
            qs = qs.filter(slug=target_slug)

        if not qs.exists():
            self.stdout.write("No converted prospects found.")
            return

        created_count = 0
        skipped_count = 0

        for prospect in qs:
            group = prospect.converted_to_group

            if Client.objects.filter(group=group).exists():
                self.stdout.write(
                    f"  SKIP  {prospect.slug} → {group.slug} (Client already exists)"
                )
                skipped_count += 1
                continue

            self.stdout.write(
                f"  {'(dry) ' if dry_run else ''}CREATE  {prospect.slug} → {group.slug}"
            )
            if not dry_run:
                with transaction.atomic():
                    Client.objects.create(
                        group=group,
                        prospect=prospect,
                        primary_contact_name=prospect.primary_contact_name,
                        primary_contact_email=prospect.primary_contact_email,
                        primary_contact_phone=prospect.primary_contact_phone,
                        website=prospect.website,
                        business_type=prospect.business_type,
                    )
            created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'Would create' if dry_run else 'Created'} {created_count} Client record(s). "
                f"Skipped {skipped_count} (already existed)."
            )
        )
