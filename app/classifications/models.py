# classifications/models.py

from django.utils.translation import gettext_lazy as _

from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

from fundamentals.bases import BaseModel
from fundamentals.models import BaseClassification
from fundamentals.validators import AllowedContentTypesMixin

class Category(BaseClassification):
    class Meta:
        verbose_name_plural=_("Categories")


class Tag(BaseClassification):
    pass


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
