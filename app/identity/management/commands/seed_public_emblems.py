# apps/identity/management/commands/seed_public_emblems.py
# HYBRID APPROACH

from django.core.management.base import BaseCommand
from identity.models import EmblemAvatar, EmblemAvatarType
import random

from identity.services.emblem_service import EmblemRenderer

NATURE_SEEDS = [
    "acorn", "birch", "cedar", "daisy", "elm", "fern", "grove", "hazel",
    "ivy", "juniper", "kelp", "lotus", "maple", "nettle", "oak", "pine",
    "quartz", "redwood", "sage", "thyme", "urchin", "violet", "willow",
    "yarrow", "zinnia", "bamboo", "clover", "dogwood", "eucalyptus", "fennel"
]

COLORS = [
    "#2F855A", "#38A169", "#48BB78",  # greens
    "#2C7A7B", "#319795", "#4FD1C5",  # teals
    "#2B6CB0", "#3182CE", "#4299E1",  # blues
    "#7C3AED", "#8B5CF6", "#A78BFA",  # purples
    "#D69E2E", "#ECC94B", "#F6E05E",  # yellows
]

def seed_public_emblems(pre_render=True):
    """
    Create public emblems.

    Args:
        pre_render: If True, immediately render all images.
                   If False, images render on first use (lazy).
    """
    from django.contrib.contenttypes.models import ContentType
    from django.conf import settings
    from groups.models import Group

    created = 0
    renderer = EmblemRenderer() if pre_render else None

    # Get default group slug from settings
    default_slug = getattr(settings, 'MIXTAPE_DEFAULT_GROUP_SLUG', 'crossroads')

    # Get or create default group as sponsor
    default_group = Group.objects.filter(slug=default_slug).first()
    if not default_group:
        print(f"Warning: Default '{default_slug}' group not found. Using first available group.")
        default_group = Group.objects.first()

    if not default_group:
        raise ValueError("No groups exist. Create at least one group before seeding emblems.")

    group_ct = ContentType.objects.get_for_model(Group)

    # Get emblem types
    dicebear_identicon = EmblemAvatarType.objects.filter(
        engine="dicebear", style="identicon"
    ).first()

    # boring_beam = EmblemAvatarType.objects.filter(
    #     engine="boring", style="beam"
    # ).first()

    initials_type = EmblemAvatarType.objects.filter(
        engine="initials", style="rounded"
    ).first()

    dicebear_shapes = EmblemAvatarType.objects.filter(
        engine="dicebear", style="shapes"
    ).first()

    # Create DiceBear identicons (pre-render these - they're the main library)
    if dicebear_identicon:
        for seed in NATURE_SEEDS[:15]:
            emblem, was_created = EmblemAvatar.objects.get_or_create(
                type=dicebear_identicon,
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
                    print(f"  Rendering {seed}...", end=" ")
                    success = renderer.render_and_upload(emblem)
                    print("✓" if success else "✗")

    if dicebear_shapes:
        for seed in NATURE_SEEDS[15:25]:
            emblem, was_created = EmblemAvatar.objects.get_or_create(
                type=dicebear_shapes,  # Changed from boring_beam
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

    # Create initials (pre-render - they're fast)
    if initials_type:
        initials_pairs = ["EL", "PC", "NB", "RG", "CC"]
        for init in initials_pairs:
            emblem, was_created = EmblemAvatar.objects.get_or_create(
                type=initials_type,
                seed=init.lower(),
                initials=init,
                defaults={
                    "sponsor_content_type": group_ct,
                    "sponsor_object_id": default_group.id,
                    "reuse_policy": EmblemAvatar.REUSE_ANYONE,
                    "license": EmblemAvatar.LICENSE_CC0,
                    "is_unlisted": False,
                    "fg": "#FFFFFF",
                    "bg": random.choice(COLORS),
                }
            )

            if was_created:
                created += 1
                if renderer:
                    print(f"  Rendering {init}...", end=" ")
                    success = renderer.render_and_upload(emblem)
                    print("✓" if success else "✗")

    return created


class Command(BaseCommand):
    help = "Seed public emblems for users to choose from"

    def add_arguments(self, parser):
        parser.add_argument(
            '--lazy',
            action='store_true',
            help='Skip pre-rendering (render on first use)',
        )

    def handle(self, *args, **kwargs):
        pre_render = not kwargs['lazy']

        if pre_render:
            self.stdout.write("Creating and pre-rendering emblems...")
        else:
            self.stdout.write("Creating emblems (will render on first use)...")

        created = seed_public_emblems(pre_render=pre_render)

        self.stdout.write(
            self.style.SUCCESS(f"✓ Created {created} public EmblemAvatar entries")
        )