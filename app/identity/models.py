# apps/identity/models.py

import uuid
from django.db import models
from django.core.validators import RegexValidator

from fundamentals.models import BaseContent
from utils.storage.storage_utils import key_to_url

HEX = RegexValidator(regex=r"^#?[0-9A-Fa-f]{6}$", message="Use #RRGGBB")

class EmblemAvatarType(models.Model):
    """
    Catalog of supported emblem/avatar engines and styles.
    Examples: ("dicebear","identicon"), ("boring","beam"), ("upload","image")
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    engine = models.CharField(max_length=32)   # dicebear|boring|jdenticon|initials|upload
    style  = models.CharField(max_length=64)   # per-engine style
    label  = models.CharField(max_length=64)

    is_upload    = models.BooleanField(default=False)
    is_generator = models.BooleanField(default=True)

    # Hints that help UI/validation
    supports_fg       = models.BooleanField(default=True)
    supports_bg       = models.BooleanField(default=True)
    supports_initials = models.BooleanField(default=False)

    CATEGORY_ABSTRACT = "abstract"
    CATEGORY_PERSON = "person"
    CATEGORY_UPLOAD = "upload"
    CATEGORY_CUSTOM = "custom"

    CATEGORY_CHOICES = [
        (CATEGORY_ABSTRACT, "Abstract"),
        (CATEGORY_PERSON, "Person"),
        (CATEGORY_UPLOAD, "Upload"),
        (CATEGORY_CUSTOM, "Custom"),
    ]

    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, default=CATEGORY_ABSTRACT)

    class Meta:
        unique_together = [("engine", "style")]
        indexes = [models.Index(fields=["engine", "style"])]

    def __str__(self):
        return f"{self.engine}:{self.style}"


class EmblemAvatar(BaseContent):
    """
    First-class, shareable emblem *content* (upload or generator).
    - Ownership uses BaseContent.sponsor (User or Group via GenericFK).
    - Reuse policy + license control who else can attach it and how it's credited.
    - Can be tagged/categorized/attached via BaseContent relations.
    - Can be attached by UserProfile.avatar and Group.emblem (FKs below).
    """

    # What *kind* of emblem it is
    type = models.ForeignKey(EmblemAvatarType, on_delete=models.PROTECT, related_name="emblems")

    # Reuse / visibility / licensing
    REUSE_ANYONE       = "anyone"       # anyone can attach
    REUSE_OWNER_ONLY   = "owner_only"   # only the sponsor/owner can attach
    REUSE_PUBLIC_ATTR  = "public_attr"  # anyone can attach, attribution required
    REUSE_CHOICES = [
        (REUSE_ANYONE, "Anyone can attach"),
        (REUSE_OWNER_ONLY, "Owner only"),
        (REUSE_PUBLIC_ATTR, "Anyone with attribution"),
    ]
    reuse_policy = models.CharField(max_length=16, choices=REUSE_CHOICES, default=REUSE_ANYONE)

    # Unlisted → not shown in public galleries, but attachable by ID
    is_unlisted = models.BooleanField(default=False)

    LICENSE_CC0         = "CC0"
    LICENSE_CC_BY       = "CC-BY"
    LICENSE_CC_BY_SA    = "CC-BY-SA"
    LICENSE_PROPRIETARY = "PRO"
    LICENSE_CHOICES = [
        (LICENSE_CC0, "CC0 (Public Domain)"),
        (LICENSE_CC_BY, "CC BY"),
        (LICENSE_CC_BY_SA, "CC BY-SA"),
        (LICENSE_PROPRIETARY, "Proprietary"),
    ]
    license = models.CharField(max_length=16, choices=LICENSE_CHOICES, default=LICENSE_PROPRIETARY)
    attribution_text = models.CharField(max_length=255, blank=True, default="")
    attribution_url  = models.URLField(blank=True, default="")

    # Source data (upload OR generator)
    image_path    = models.CharField(max_length=512, blank=True)   # for uploads
    seed          = models.CharField(max_length=128, blank=True)   # for generators
    style_variant = models.CharField(max_length=64, blank=True)
    fg = models.CharField(max_length=7, blank=True, validators=[HEX])
    bg = models.CharField(max_length=7, blank=True, validators=[HEX])
    initials = models.CharField(max_length=4, blank=True)

    # Cross-DB friendly list of hex colors
    palette = models.JSONField(blank=True, default=list)

    # Cached/rendition URLs (filled by workers)
    size_48      = models.CharField(max_length=512, blank=True)
    size_96      = models.CharField(max_length=512, blank=True)
    size_192     = models.CharField(max_length=512, blank=True)
    size_512     = models.CharField(max_length=512, blank=True)
    og_1200x630  = models.CharField(max_length=512, blank=True)

    class Meta(BaseContent.Meta):
        ordering = ("-updated_at",)

        # Only Emblem-specific indexes here.
        indexes = [
            # frequent filters / lookups
            models.Index(fields=["type"]),
            models.Index(fields=["reuse_policy"]),
            models.Index(fields=["license"]),
            models.Index(fields=["is_unlisted"]),
            models.Index(fields=["seed"]),
            # helpful when listing “my emblems” by owner/sponsor
            models.Index(fields=["sponsor_content_type", "sponsor_object_id"]),
        ]

    def __str__(self):
        who = getattr(self.sponsor, "display_name", str(self.sponsor)) if self.sponsor else "∅"
        base = self.image_path or self.seed or str(self.pk)
        return f"Emblem[{self.type}] {base} • owner={who}"

    # Convenience guard (used in permissions/serializers)
    def can_be_attached_by(self, actor) -> bool:
        """
        Allow attach if:
        - reuse_policy = anyone/public_attr, or
        - reuse_policy = owner_only and actor is the sponsor (User or Group)
        Staff overrides can be added in view/permission layer.
        """
        if self.reuse_policy in (self.REUSE_ANYONE, self.REUSE_PUBLIC_ATTR):
            return True
        # owner-only: must match sponsor
        return bool(actor and self.sponsor and actor == self.sponsor)

    @property
    def size_48_url(self): return key_to_url(self.size_48)

    @property
    def size_96_url(self): return key_to_url(self.size_96)

    @property
    def size_192_url(self): return key_to_url(self.size_192)

    @property
    def size_512_url(self): return key_to_url(self.size_512)

    @property
    def og_1200x630_url(self): return key_to_url(self.og_1200x630)
