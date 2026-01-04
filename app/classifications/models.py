# classifications/models.py

from django.utils.translation import gettext_lazy as _

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from fundamentals.bases import BaseModel
from fundamentals.models import BaseClassification
from fundamentals.validators import AllowedContentTypesMixin

class Category(BaseClassification):
    """
    Sponsor-scoped categories for content organization.
    Each group/user has their own category namespace.
    """

    # Polymorphic sponsor (Group or User)
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    class Meta(BaseClassification.Meta):
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        constraints = [
            # Unique slug per sponsor
            models.UniqueConstraint(
                fields=['sponsor_content_type', 'sponsor_object_id', 'slug'],
                name='category_slug_sponsor_unique'
            )
        ]
        indexes = [
            models.Index(fields=['sponsor_content_type', 'sponsor_object_id']),
            models.Index(fields=['sponsor_content_type', 'sponsor_object_id', 'slug']),
        ]

    def slug_exists(self, slug: str) -> bool:
        """
        Override: Check slug uniqueness within sponsor scope.
        """
        if not hasattr(self, 'sponsor_content_type') or not self.sponsor_object_id:
            return False

        return self.__class__.objects.filter(
            sponsor_content_type=self.sponsor_content_type,
            sponsor_object_id=self.sponsor_object_id,
            slug=slug
        ).exclude(pk=self.pk).exists()

    def __str__(self):
        sponsor_name = getattr(
            self.sponsor,
            'title',
            getattr(self.sponsor, 'display_name', str(self.sponsor))
        )
        return f"{sponsor_name} — {self.title}"


class Tag(BaseClassification):
    """
    Platform-wide tags for content discovery.
    Slugs are globally unique across all tags.
    """

    class Meta(BaseClassification.Meta):
        verbose_name = "Tag"
        verbose_name_plural = "Tags"
        constraints = [
            models.UniqueConstraint(
                fields=['slug'],
                name='tag_slug_unique'
            )
        ]

    def __str__(self):
        return self.title or "Unnamed Tag"


class ClassificationUsage(BaseModel, AllowedContentTypesMixin):

    allowed_models = ["tag", "category"]

    # Generic relation to the client (e.g. Post, Document, etc.)
    # Using CharField to support both integer PKs and UUIDs
    classification_client_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    classification_client_object_id = models.CharField(max_length=255, db_index=True)
    classification_client = GenericForeignKey(
        "classification_client_content_type",
        "classification_client_object_id"
    )

    # Generic relation to the classifier (Tag or Category)
    # Tags/Categories use integer PKs from BaseModel
    classification_content_type = models.ForeignKey(ContentType, related_name="classifier_type", on_delete=models.CASCADE)
    classification_object_id = models.PositiveIntegerField(db_index=True)
    classification = GenericForeignKey(
        "classification_content_type",
        "classification_object_id"
    )

    role = models.CharField(max_length=50, blank=True, default="")  # Optional

    class Meta:
        verbose_name = "Classification Usage"
        verbose_name_plural = "Classification Usages"

        # Performance indexes for GenericForeignKey queries
        indexes = [
            # Query by content (e.g., "get all tags for this WritingPiece")
            models.Index(
                fields=['classification_client_content_type', 'classification_client_object_id'],
                name='classif_client_idx'
            ),
            # Query by classification (e.g., "get all WritingPieces with this tag")
            models.Index(
                fields=['classification_content_type', 'classification_object_id'],
                name='classif_idx'
            ),
            # Combined query for filtering
            models.Index(
                fields=[
                    'classification_client_content_type',
                    'classification_client_object_id',
                    'classification_content_type'
                ],
                name='classif_combined_idx'
            ),
        ]

        # Prevent duplicate assignments
        unique_together = [
            ('classification_client_content_type', 'classification_client_object_id',
             'classification_content_type', 'classification_object_id')
        ]

    def __str__(self):
        return f"{self.classification} used in {self.classification_client}"

    def clean(self):
        self.validate_content_type(self.classification_content_type)
