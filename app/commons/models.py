# commons/models.py

from django.contrib.auth import get_user_model
from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent


User = get_user_model()


class CommonsItem(BaseContent):
    """
    A curated entry in the Crossroads Commons atlas.

    Inherits from BaseContent:
      id (UUID), title, summary, slug, body, submitted_by, author,
      sponsor GFK, tags/categories via GenericRelation, published_at,
      created_at, updated_at, deleted_at.
    """

    class ItemType(models.TextChoices):
        PERSON = "person", "Person"
        ORGANIZATION = "organization", "Organization"
        GROUP = "group", "Group"
        PROJECT = "project", "Project"
        PLACE = "place", "Place"
        EVENT = "event", "Event"

    class CurationStatus(models.TextChoices):
        CAPTURED = "captured", "Captured"
        IN_CURATION = "in_curation", "In Curation"
        READY = "ready", "Ready for Review"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    # Type
    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices,
        blank=True,
        default="",
    )

    # Curation workflow
    curation_status = models.CharField(
        max_length=20,
        choices=CurationStatus.choices,
        default=CurationStatus.CAPTURED,
        db_index=True,
    )

    # Human recommendation
    recommended_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commons_recommendations",
    )
    why_recommended = models.TextField(blank=True, default="")

    # External links
    website = models.URLField(max_length=500, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_links = models.JSONField(default=list, blank=True)
    instagram = models.URLField(max_length=500, blank=True, default="")
    youtube = models.URLField(max_length=500, blank=True, default="")
    rss = models.URLField(max_length=500, blank=True, default="")

    # Geographic
    location_name = models.CharField(max_length=255, blank=True, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    # Extraction
    source_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Original submitted URL",
    )
    extracted_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw extraction output from Inkwell",
    )
    additional_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible metadata (hours, pricing, etc.)",
    )

    # Curation tracking
    curated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commons_curations",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commons_approvals",
    )

    # Founder (text for now, Filament relationship later)
    founder = models.CharField(max_length=255, blank=True, default="")

    class Meta(BaseContent.Meta):
        indexes = BaseContent.Meta.indexes + [
            models.Index(fields=["curation_status"]),
            models.Index(fields=["item_type"]),
            models.Index(fields=["curation_status", "-created_at"]),
        ]

    def __str__(self):
        return self.title or f"CommonsItem {self.pk}"


class Filament(BaseModel):
    """
    A typed relationship between two CommonsItems.
    Forms the relational layer (Tapestry) of the Commons atlas.
    """

    class RelationType(models.TextChoices):
        FOUNDED_BY = "founded_by", "Founded By"
        LOCATED_IN = "located_in", "Located In"
        COLLABORATES_WITH = "collaborates_with", "Collaborates With"
        TEACHES_AT = "teaches_at", "Teaches At"
        INSPIRED_BY = "inspired_by", "Inspired By"
        AFFILIATED_WITH = "affiliated_with", "Affiliated With"
        PROGRAM_OF = "program_of", "Program Of"

    source = models.ForeignKey(
        CommonsItem,
        on_delete=models.CASCADE,
        related_name="filaments_out",
    )
    target = models.ForeignKey(
        CommonsItem,
        on_delete=models.CASCADE,
        related_name="filaments_in",
    )
    relation_type = models.CharField(
        max_length=30,
        choices=RelationType.choices,
    )
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "relation_type"],
                name="commons_filament_unique_relation",
            )
        ]

    def __str__(self):
        return f"{self.source} —[{self.relation_type}]→ {self.target}"
