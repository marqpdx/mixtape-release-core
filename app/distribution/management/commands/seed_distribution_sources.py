# distribution/management/commands/seed_distribution_sources.py
"""
Seed default distribution Sources.

Usage:
    python manage.py seed_distribution_sources
    python manage.py seed_distribution_sources --group <slug>   # also seed activity_stream for a group

Creates:
    - linkedin  (global, tier=free) — personal share-link
    - activity_stream for each group passed via --group (tier=free)

Idempotent: safe to run multiple times. Uses get_or_create on (kind, group).
"""
from django.core.management.base import BaseCommand, CommandError

from distribution.models import Source, SourceKind


GLOBAL_SOURCES = [
    {
        "kind": SourceKind.LINKEDIN,
        "label": "LinkedIn",
        "tier_required": "free",
        "config_schema": {"post_copy": {"type": "string", "required": False}},
        "group": None,
    },
]


class Command(BaseCommand):
    help = "Seed default distribution Sources (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--group",
            dest="group_slugs",
            nargs="*",
            metavar="SLUG",
            help="Slug(s) of groups to seed an activity_stream source for.",
        )

    def handle(self, *args, **options):
        created_count = 0

        # Global sources (group=None)
        for spec in GLOBAL_SOURCES:
            _, created = Source.objects.get_or_create(
                kind=spec["kind"],
                group=None,
                defaults={
                    "label": spec["label"],
                    "tier_required": spec["tier_required"],
                    "config_schema": spec["config_schema"],
                    "is_active": True,
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"  Created: {spec['kind']} (global)")
            else:
                self.stdout.write(f"  Exists:  {spec['kind']} (global)")

        # Group-scoped activity_stream sources
        group_slugs = options.get("group_slugs") or []
        if group_slugs:
            from groups.models import Group
            for slug in group_slugs:
                try:
                    group = Group.objects.get(slug=slug)
                except Group.DoesNotExist:
                    raise CommandError(f"Group '{slug}' not found.")

                _, created = Source.objects.get_or_create(
                    kind=SourceKind.ACTIVITY_STREAM,
                    group=group,
                    defaults={
                        "label": f"{group.name} Activity Stream",
                        "tier_required": "free",
                        "config_schema": {},
                        "is_active": True,
                    },
                )
                if created:
                    created_count += 1
                    self.stdout.write(f"  Created: activity_stream for group '{slug}'")
                else:
                    self.stdout.write(f"  Exists:  activity_stream for group '{slug}'")

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {created_count} source(s) created."
        ))
