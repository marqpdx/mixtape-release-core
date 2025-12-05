from django.db import models


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, default=None)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


    @classmethod
    def get_field_metadata(cls):
        fields_metadata = []
        for field in cls._meta.fields:
            field_type = type(field).__name__
            field_info = {
                "name": field.name,
                "type": field_type,
                "required": not field.blank  # `blank` controls if the field is required in forms
            }
            fields_metadata.append(field_info)
        return fields_metadata


class BaseCollection(BaseModel):
    class Meta:
        abstract = True
