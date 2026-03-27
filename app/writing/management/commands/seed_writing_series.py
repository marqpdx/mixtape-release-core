# writing/management/commands/seed_writing_series.py
"""
Seed WritingSeries records from the Article Calendar phases.

Usage:
    python manage.py seed_writing_series --group <slug>
    python manage.py seed_writing_series --group crossroads --dry-run

Each series maps to a Phase in the Article Calendar. Records are created
with get_or_create, so the command is idempotent — safe to re-run.

The import pipeline resolves `phase: <int>` frontmatter to a WritingSeries
by matching phase_num. If no match is found, import fails with a validation
error rather than silently skipping.
"""

from django.core.management.base import BaseCommand, CommandError


CALENDAR_PHASES = [
    {
        "phase_num": 0,
        "title": "Welcome",
        "slug": "phase-0-welcome",
        "subtitle": "Framing the series, the practice of AI-Collab, and an invitation to explore.",
    },
    {
        "phase_num": 1,
        "title": "Launch & Demonstration",
        "slug": "phase-1-launch-demonstration",
        "subtitle": "Dogfood series: using our own system to publish, the Mixtape process, and real-world coherence enforcement.",
    },
    {
        "phase_num": 2,
        "title": "Foundations",
        "slug": "phase-2-foundations",
        "subtitle": "Core philosophy: software as experiments in coherence, AI-Collab and the new craft, the challenge of coherence.",
    },
    {
        "phase_num": 3,
        "title": "Emergence & Practice",
        "slug": "phase-3-emergence-practice",
        "subtitle": "Emergent software, fidelity and ownership, the Many Small Pattern, long-thinking, and stable substrates.",
    },
    {
        "phase_num": 4,
        "title": "Systems & Patterns",
        "slug": "phase-4-systems-patterns",
        "subtitle": "The Reviewer Pattern, continuous auditability, pipelining, shared context, and canon.",
    },
    {
        "phase_num": 5,
        "title": "Tooling Evolution",
        "slug": "phase-5-tooling-evolution",
        "subtitle": "Emergent tooling, Puddlejump deep dives, and the demo library.",
    },
    {
        "phase_num": 6,
        "title": "Roles & Teams",
        "slug": "phase-6-roles-teams",
        "subtitle": "AI-native roles, team optimization, and ownership as structure.",
    },
    {
        "phase_num": 7,
        "title": "Real-World Application",
        "slug": "phase-7-real-world-application",
        "subtitle": "The LinkedIn pipeline, from idea to deployment, maintaining systems over time.",
    },
    {
        "phase_num": 8,
        "title": "Advanced Concepts",
        "slug": "phase-8-advanced-concepts",
        "subtitle": "Multi-agent coordination, work as threads, the future of software craft.",
    },
]


class Command(BaseCommand):
    help = "Seed WritingSeries records from the Article Calendar phases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--group",
            type=str,
            required=True,
            help="Group slug to attach series to",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would be created without writing to the database",
        )

    def handle(self, *args, **options):
        from groups.models import Group
        from writing.models import WritingSeries

        group_slug = options["group"]
        dry_run = options["dry_run"]

        try:
            group = Group.objects.get(slug=group_slug)
        except Group.DoesNotExist:
            raise CommandError(f"Group with slug '{group_slug}' not found.")

        self.stdout.write(
            f"{'[DRY RUN] ' if dry_run else ''}Seeding {len(CALENDAR_PHASES)} series for group '{group.slug}'..."
        )

        created_count = 0
        existing_count = 0

        for phase in CALENDAR_PHASES:
            if dry_run:
                exists = WritingSeries.objects.filter(group=group, slug=phase["slug"]).exists()
                action = "exists" if exists else "would create"
                self.stdout.write(
                    f"  [{action}] Phase {phase['phase_num']}: {phase['title']} ({phase['slug']})"
                )
                if not exists:
                    created_count += 1
                else:
                    existing_count += 1
                continue

            series, created = WritingSeries.objects.get_or_create(
                group=group,
                slug=phase["slug"],
                defaults={
                    "title": phase["title"],
                    "phase_num": phase["phase_num"],
                    "subtitle": phase["subtitle"],
                },
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"  Created: Phase {series.phase_num} — {series.title}")
                )
            else:
                existing_count += 1
                self.stdout.write(f"  Already exists: Phase {series.phase_num} — {series.title}")

        self.stdout.write(
            f"\n{'[DRY RUN] ' if dry_run else ''}Done. "
            f"Created: {created_count}, Already existed: {existing_count}"
        )
