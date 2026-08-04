# groups/models/page_component.py
#
# Ad hoc content blocks for a Crossroads Page (DB-0002).
# Each component belongs to a page, occupies a named slot, and carries its
# content as typed JSON. Sort order controls display sequence within a slot.

from django.db import models


class PageComponent(models.Model):
    """
    A freeform content block attached to a PublicPage slot.

    component_type determines the shape of content_json:
      text    — {heading?: str, body: str}
      image   — {url: str, alt?: str, caption?: str}
      link    — {label: str, url: str, description?: str}
      callout — {heading: str, body: str, style?: "info"|"highlight"}
    """

    class ComponentType(models.TextChoices):
        TEXT = "text", "Text"
        IMAGE = "image", "Image"
        LINK = "link", "Link"
        CALLOUT = "callout", "Callout"

    page = models.ForeignKey(
        "groups.PublicPage",
        on_delete=models.CASCADE,
        related_name="components",
    )
    slot = models.CharField(
        max_length=64,
        help_text="Named slot on the page layout (e.g. 'about', 'links', 'cta').",
    )
    component_type = models.CharField(max_length=20, choices=ComponentType.choices)
    content_json = models.JSONField(default=dict)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "groups"
        ordering = ["slot", "sort_order", "created_at"]

    def __str__(self):
        return f"PageComponent({self.page.group.slug}, {self.slot}, {self.component_type})"
