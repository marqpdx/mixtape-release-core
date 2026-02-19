# fundamentals/mixins.py

from django.db import models


class FlowMode(models.TextChoices):
    SEQUENCED = "sequenced", "Sequenced"
    CURATED = "curated", "Curated"
    LOOSE = "loose", "Loose"


class CuratedSequenceMixin(models.Model):
    """
    Abstract mixin for containers that present ordered content.

    Flow modes:
    - sequenced: strict linear progression (courses, modules)
    - curated: editorial ordering matters but non-linear navigation allowed
    - loose: unordered collection (default for libraries)
    """

    flow_mode = models.CharField(
        max_length=16,
        choices=FlowMode.choices,
        default=FlowMode.LOOSE,
        db_index=True,
    )

    class Meta:
        abstract = True
