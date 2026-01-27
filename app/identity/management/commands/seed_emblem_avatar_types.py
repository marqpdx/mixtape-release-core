# apps/identity/management/commands/seed_emblem_avatar_types.py
from django.core.management.base import BaseCommand
from identity.models import EmblemAvatarType


CATALOG = [
    dict(engine="upload", style="image", label="Uploaded image", category="upload", is_upload=True, is_generator=False, supports_fg=False, supports_bg=False),
    dict(engine="initials", style="rounded", label="Initials", category="abstract", supports_initials=True),
    dict(engine="dicebear", style="identicon", label="Identicon", category="abstract"),
    dict(engine="dicebear", style="shapes", label="Shapes", category="abstract"),
    dict(engine="dicebear", style="lorelei", label="Lorelei", category="person"),
    dict(engine="dicebear", style="croodles", label="Croodles", category="person"),
    dict(engine="dicebear", style="big-ears", label="Big Ears", category="person"),
]

def seed_emblem_types(silent=False):
    created = 0
    for item in CATALOG:
        _, was_created = EmblemAvatarType.objects.get_or_create(
            engine=item["engine"], style=item["style"], defaults=item
        )
        created += int(was_created)
    return created

class Command(BaseCommand):
    help = "Seed emblem avatar types"

    def handle(self, *args, **kwargs):
        created = seed_emblem_types()
        self.stdout.write(self.style.SUCCESS(f"Seeded {created} EmblemAvatarType entries"))
