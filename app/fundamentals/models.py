# fundamentals/models.py
# ============================================================================
# PHASE 2: Minimal Content Models for Groups
# ============================================================================
# This file contains BaseContent and LayoutParent needed by the Groups app.
# Full implementation will be added in Phase 4+ when we add content creation.
# For now, we provide minimal abstract base classes.
# ============================================================================

from django.db import models
from django.template.defaultfilters import slugify
from django.utils.crypto import get_random_string
from .bases import BaseModel

def default_slug():
    """Generate a random slug for content that hasn't been given a slug yet"""
    return f"temp-{get_random_string(8)}"

class BaseContent(BaseModel):
    """
    Minimal abstract base for content-like models (Groups, Posts, etc.)
    Phase 2: Just the essentials for Groups
    Phase 4+: Will add sponsor relationships, visibility, etc.
    """
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, db_index=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class LayoutParent(models.Model):
    """
    Minimal abstract base for models that can have layouts
    Phase 2: Placeholder for Groups
    Phase 4+: Will add actual layout functionality
    """
    class Meta:
        abstract = True


# ============================================================================
# DEFERRED TO PHASE 4+ (Full Content Creation Features)
# ============================================================================
# The following models are commented out for Phase 2:
# - BaseData (polymorphic content relationships)
# - Asset management integration
# - Sponsor models (polymorphic sponsors)
# - Full visibility/privacy controls
#
# Will uncomment when we add content creation features.
# ============================================================================
