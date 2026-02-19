# apps/identity/management/commands/fix_missing_emblem_renders.py

from django.core.management.base import BaseCommand
from identity.models import EmblemAvatar
from identity.services.emblem_service import EmblemRenderer

class Command(BaseCommand):
    help = "Re-render emblems that are missing size URLs (or all, with --force)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be rendered without actually rendering',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-render all emblems, even if URLs already exist',
        )

    def handle(self, *args, **kwargs):
        dry_run = kwargs['dry_run']
        force = kwargs['force']

        # Find emblems missing URLs (or all if forced)
        missing = EmblemAvatar.objects.all() if force else EmblemAvatar.objects.filter(size_96='')
        count = missing.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("✓ All emblems have URLs"))
            return

        self.stdout.write(f"Found {count} emblems{'' if force else ' without URLs'}:")
        for emblem in missing:
            label = emblem.seed or emblem.initials or str(emblem.id)[:8]
            self.stdout.write(f"  - {label} ({emblem.type.engine}:{emblem.type.style})")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n--dry-run enabled, not rendering"))
            return

        # Re-render
        self.stdout.write("\nRendering...")
        renderer = EmblemRenderer()
        success_count = 0

        for emblem in missing:
            label = emblem.seed or emblem.initials or str(emblem.id)[:8]
            self.stdout.write(f"  Rendering {label}...", ending=" ")

            success = renderer.render_and_upload(emblem)
            if success:
                self.stdout.write(self.style.SUCCESS("✓"))
                success_count += 1
            else:
                self.stdout.write(self.style.ERROR("✗"))

        self.stdout.write(
            self.style.SUCCESS(f"\n✓ Successfully rendered {success_count}/{count} emblems")
        )
