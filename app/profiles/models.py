# profiles/models.py

import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.template.defaultfilters import slugify

from fundamentals.bases import BaseModel


class UserProfile(BaseModel):
    """
    Minimal user profile model for Phase 1.
    Represents public-facing member information (1:1 with User).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)

    user = models.OneToOneField(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="profile"
    )

    slug = models.SlugField(unique=True, max_length=99)
    display_name = models.CharField(max_length=48, help_text="Your public facing screen name.")
    quick_intro = models.TextField(max_length=300, default="", blank=True, help_text="A quick bit about yourself.")
    right_now = models.TextField(max_length=200, default="", blank=True, help_text="A few words how you are right now (totally optional).")
    skills = models.TextField(max_length=400, default="", blank=True, help_text="Skills, capacities, or areas of expertise.")
    work_areas = models.TextField(max_length=400, default="", blank=True, help_text="Work areas, focus areas, or domains of current activity.")
    practice_area = models.CharField(max_length=120, default="", blank=True, help_text="Primary practice area or discipline (e.g. Product, Engineering, Design).")
    location = models.CharField(max_length=120, default="", blank=True, help_text="City, region, or remote.")
    quick_link = models.URLField(max_length=512, default="", blank=True, help_text="Personal or work link (website, IG, etc.)")
    who_are_you = models.CharField(max_length=512, default="", blank=True, help_text="How you'd describe yourself to the group.")
    why_are_you_here = models.CharField(max_length=512, default="", blank=True, help_text="Why you joined / what you're looking for.")
    intro_voice = models.CharField(max_length=512, default="", blank=True, help_text="Storage key for intro voice note audio file.")
    intro_voice_transcript = models.TextField(default="", blank=True, help_text="Auto-generated transcript of intro voice note.")

    # Placeholder for avatar/images (next phase - will use actual file storage)
    avatar_url = models.CharField(max_length=512, default="", blank=True, help_text="Avatar image URL")
    profile_image = models.CharField(max_length=512, default="", blank=True, help_text="Profile image storage key")
    background_image = models.CharField(max_length=512, default="", blank=True, help_text="Background image storage key")
    bio_json = models.JSONField(blank=True, default=dict)
    bio_markdown = models.TextField(max_length=2000, blank=True, default="")
    preferences = models.JSONField(blank=True, default=dict, help_text="User UI preferences (e.g. dashboard settings).")

    def save(self, *args, **kwargs):
        # Auto-generate slug from display_name or username
        if not self.slug:
            base = slugify(self.display_name or self.user.username)
            slug = base
            counter = 1
            while UserProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{counter}"
                counter += 1
            self.slug = slug

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile: {self.display_name} (@{self.user.username})"

    class Meta:
        app_label = "profiles"
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"


# ─── Profile Revamp models ────────────────────────────────────────────────────

class ThemeChoices(models.TextChoices):
    PAPER  = 'paper',  'Paper'
    NOIR   = 'noir',   'Noir'
    GARDEN = 'garden', 'Garden'
    NEON   = 'neon',   'Neon'
    SUNSET = 'sunset', 'Sunset'


class FontChoices(models.TextChoices):
    EDITORIAL = 'editorial', 'Editorial'
    MODERN    = 'modern',    'Modern'
    MONO      = 'mono',      'Mono'
    PLAYFUL   = 'playful',   'Playful'


class BgChoices(models.TextChoices):
    NONE     = 'none',     'None'
    PAPER    = 'paper',    'Paper'
    GRID     = 'grid',     'Grid'
    LEAVES   = 'leaves',   'Leaves'
    SUNSET   = 'sunset',   'Sunset'
    HALFTONE = 'halftone', 'Halftone'


class AvatarShapeChoices(models.TextChoices):
    ROUNDED = 'rounded', 'Rounded'
    CIRCLE  = 'circle',  'Circle'
    SQUARE  = 'square',  'Square'
    BLOB    = 'blob',    'Blob'


class DensityChoices(models.TextChoices):
    COMPACT = 'compact', 'Compact'
    COZY    = 'cozy',    'Cozy'
    ROOMY   = 'roomy',   'Roomy'


class LinkIconChoices(models.TextChoices):
    IG = 'IG', 'Instagram'
    SH = 'SH', 'Shop'
    NL = 'NL', 'Newsletter'
    PR = 'PR', 'Patreon'
    BC = 'BC', 'Bandcamp'
    SC = 'SC', 'SoundCloud'
    YT = 'YT', 'YouTube'
    EM = 'EM', 'Email'
    IT = 'IT', 'itch.io'
    BG = 'BG', 'BoardGameGeek'


KNOWN_SECTION_IDS = ['header', 'pinned', 'now', 'activity', 'friends', 'qa', 'badges', 'links']

DEFAULT_SECTION_LAYOUT = [
    {'id': 'header',   'visible': True},
    {'id': 'pinned',   'visible': True},
    {'id': 'now',      'visible': True},
    {'id': 'activity', 'visible': True},
    {'id': 'friends',  'visible': True},
    {'id': 'qa',       'visible': True},
    {'id': 'badges',   'visible': True},
    {'id': 'links',    'visible': True},
]


class ProfileTheme(models.Model):
    profile = models.OneToOneField(
        UserProfile, on_delete=models.CASCADE, related_name='theme_config'
    )
    theme        = models.CharField(max_length=16, choices=ThemeChoices.choices, default=ThemeChoices.PAPER)
    accent       = models.CharField(max_length=7, default='#c2410c')
    font         = models.CharField(max_length=16, choices=FontChoices.choices, default=FontChoices.EDITORIAL)
    background   = models.CharField(max_length=16, choices=BgChoices.choices, default=BgChoices.PAPER)
    avatar_shape = models.CharField(max_length=16, choices=AvatarShapeChoices.choices, default=AvatarShapeChoices.ROUNDED)
    density      = models.CharField(max_length=16, choices=DensityChoices.choices, default=DensityChoices.COZY)
    decorations  = models.BooleanField(default=True)
    avatar_sticker = models.CharField(max_length=4, blank=True)
    section_layout = models.JSONField(default=list)
    version      = models.PositiveIntegerField(default=1)

    class Meta:
        app_label = "profiles"

    def __str__(self):
        return f"Theme config for {self.profile}"


class PinnedShowcase(models.Model):
    KIND_CHOICES = [('tape', 'Tape'), ('project', 'Project'), ('quote', 'Quote')]

    profile    = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='pinned_showcase')
    kind       = models.CharField(max_length=16, choices=KIND_CHOICES, default='tape')
    label      = models.CharField(max_length=40, blank=True)
    title      = models.CharField(max_length=120, blank=True)
    subtitle   = models.CharField(max_length=200, blank=True)
    mark       = models.CharField(max_length=4, blank=True)
    cover      = models.ImageField(upload_to='pinned/', null=True, blank=True)
    cta_target = models.URLField(blank=True)

    class Meta:
        app_label = "profiles"


class PinnedTrack(models.Model):
    showcase = models.ForeignKey(PinnedShowcase, on_delete=models.CASCADE, related_name='tracks')
    position = models.PositiveSmallIntegerField()
    label    = models.CharField(max_length=80, blank=True)
    name     = models.CharField(max_length=140)
    duration = models.CharField(max_length=12, blank=True)

    class Meta:
        app_label = "profiles"
        ordering = ['position']
        unique_together = [('showcase', 'position')]


class NowPlaying(models.Model):
    profile    = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='now_playing')
    track      = models.CharField(max_length=140, blank=True)
    artist     = models.CharField(max_length=140, blank=True)
    label      = models.CharField(max_length=40, blank=True)
    source     = models.CharField(max_length=16, blank=True)
    source_id  = models.CharField(max_length=128, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "profiles"


class QAItem(models.Model):
    profile  = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='qa_items')
    position = models.PositiveSmallIntegerField()
    q        = models.CharField(max_length=30)
    a        = models.TextField(max_length=400)

    class Meta:
        app_label = "profiles"
        ordering = ['position']
        unique_together = [('profile', 'position')]


class Badge(models.Model):
    profile   = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='badges')
    glyph     = models.CharField(max_length=4)
    text      = models.CharField(max_length=40)
    featured  = models.BooleanField(default=False)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "profiles"
        unique_together = [('profile', 'glyph')]


class FeaturedLink(models.Model):
    profile  = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='featured_links')
    position = models.PositiveSmallIntegerField()
    icon     = models.CharField(max_length=8, choices=LinkIconChoices.choices)
    title    = models.CharField(max_length=40)
    sub      = models.CharField(max_length=80, blank=True)
    url      = models.URLField()

    class Meta:
        app_label = "profiles"
        ordering = ['position']
        unique_together = [('profile', 'position')]
