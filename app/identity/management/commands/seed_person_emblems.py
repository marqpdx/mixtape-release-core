# apps/identity/management/commands/seed_person_emblems.py

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from identity.models import EmblemAvatar, EmblemAvatarType
from groups.models import Group
import random

PERSON_NAMES = [
    "alex", "morgan", "jordan", "taylor", "casey", "riley", "quinn", "avery",
    "dakota", "charlie", "sam", "drew", "blake", "river", "sage", "phoenix"
]

COLORS = ["#2F855A", "#2C7A7B", "#2B6CB0", "#7C3AED", "#D69E2E"]

def seed_person_emblems(pre_render=True):
    from django.contrib.contenttypes.models import ContentType
    from groups.models import Group
    from identity.services.emblem_service import EmblemRenderer

    created = 0
    renderer = EmblemRenderer() if pre_render else None

    # Get default group as sponsor
    default_slug = getattr(settings, 'MIXTAPE_DEFAULT_GROUP_SLUG', 'crossroads')
    default_group = Group.objects.filter(slug=default_slug).first()
    if not default_group:
        default_group = Group.objects.first()
    if not default_group:
        raise ValueError("No groups exist.")

    group_ct = ContentType.objects.get_for_model(Group)

    # Get person types
    croodles = EmblemAvatarType.objects.filter(engine="dicebear", style="croodles").first()
    lorelei = EmblemAvatarType.objects.filter(engine="dicebear", style="lorelei").first()
    big_ears = EmblemAvatarType.objects.filter(engine="dicebear", style="big-ears").first()

    # Create croodles
    if croodles:
        for seed in PERSON_NAMES[:6]:
            emblem, was_created = EmblemAvatar.objects.get_or_create(
                type=croodles,
                seed=seed,
                defaults={
                    "sponsor_content_type": group_ct,
                    "sponsor_object_id": default_group.id,
                    "reuse_policy": EmblemAvatar.REUSE_ANYONE,
                    "license": EmblemAvatar.LICENSE_CC0,
                    "is_unlisted": False,
                    "bg": random.choice(COLORS),
                }
            )
            if was_created:
                created += 1
                if renderer:
                    print(f"  Rendering {seed} (croodles)...", end=" ")
                    success = renderer.render_and_upload(emblem)
                    print("✓" if success else "✗")

    # Create lorelei
    if lorelei:
        for seed in PERSON_NAMES[6:11]:
            emblem, was_created = EmblemAvatar.objects.get_or_create(
                type=lorelei,
                seed=seed,
                defaults={
                    "sponsor_content_type": group_ct,
                    "sponsor_object_id": default_group.id,
                    "reuse_policy": EmblemAvatar.REUSE_ANYONE,
                    "license": EmblemAvatar.LICENSE_CC0,
                    "is_unlisted": False,
                }
            )
            created += int(was_created)

    # Create big-ears
    if big_ears:
        for seed in PERSON_NAMES[11:16]:
            emblem, was_created = EmblemAvatar.objects.get_or_create(
                type=big_ears,
                seed=seed,
                defaults={
                    "sponsor_content_type": group_ct,
                    "sponsor_object_id": default_group.id,
                    "reuse_policy": EmblemAvatar.REUSE_ANYONE,
                    "license": EmblemAvatar.LICENSE_CC0,
                    "is_unlisted": False,
                }
            )
            created += int(was_created)

    return created


class Command(BaseCommand):
    help = "Seed person-style emblems"

    def add_arguments(self, parser):
        parser.add_argument('--lazy', action='store_true', help='Skip pre-rendering')

    def handle(self, *args, **kwargs):
        pre_render = not kwargs['lazy']
        created = seed_person_emblems(pre_render=pre_render)
        self.stdout.write(self.style.SUCCESS(f"✓ Created {created} person emblems"))