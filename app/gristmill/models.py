# gristmill/models.py

from django.db import models
from django.contrib.auth import get_user_model
from fundamentals.models import BaseModel
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid

User = get_user_model()


class MillDraft(BaseModel):
    """Minimal MillDraft - no sessions for v0.1"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)

    # Source
    grist_text = models.TextField()

    # Parsed
    ast_json = models.JSONField()
    block_type = models.CharField(max_length=50)

    # Status
    status = models.CharField(
        max_length=20,
        default='staged',
        choices=[
            ('staged', 'Staged'),
            ('promoted', 'Promoted'),
            ('rejected', 'Rejected'),
        ]
    )

    # Promotion link
    promoted_at = models.DateTimeField(null=True, blank=True)
    promoted_content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    promoted_object_id = models.UUIDField(null=True, blank=True)
    promoted_object = GenericForeignKey('promoted_content_type', 'promoted_object_id')

    class Meta:
        ordering = ['-created_at']
