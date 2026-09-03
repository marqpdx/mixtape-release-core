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


class RichBodyMixin(models.Model):
    """
    Abstract mixin for models carrying ProseMirror/Tiptap body content.
    body_json is the source of truth; body_text is derived on save.
    body_html is never stored — generate at emit time via render_html_from_prosemirror.
    """

    body_json = models.JSONField(default=dict, blank=True)
    body_text = models.TextField(blank=True, default="")

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.body_json and not self.body_text:
            from utils.writing.writing_utils import extract_text_from_prosemirror
            self.body_text = extract_text_from_prosemirror(self.body_json) or ""
        super().save(*args, **kwargs)
