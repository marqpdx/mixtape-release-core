# fundamentals/validators.py

from django.core.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType


class AllowedContentTypesMixin:
    """
    Mixin to validate that a GenericForeignKey points to an allowed model.

    Usage:
        class MyModel(models.Model, AllowedContentTypesMixin):
            allowed_models = ['tag', 'category']  # Model names (lowercase)
            content_type = models.ForeignKey(ContentType, ...)
            object_id = models.PositiveIntegerField()
            content_object = GenericForeignKey('content_type', 'object_id')
    """

    allowed_models = []  # Override in subclass

    def validate_content_type(self, content_type):
        """
        Validate that the content_type is in allowed_models list.

        Args:
            content_type: ContentType instance to validate

        Raises:
            ValidationError: If content_type model is not allowed
        """
        if not self.allowed_models:
            # No restrictions if allowed_models is empty
            return

        model_name = content_type.model.lower()

        if model_name not in self.allowed_models:
            raise ValidationError(
                f"Content type '{model_name}' is not allowed. "
                f"Allowed types: {', '.join(self.allowed_models)}"
            )
