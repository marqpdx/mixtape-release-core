# groups/models/group_public_config.py

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models


class GroupPublicConfig(models.Model):
    """
    Configuration for a Group's public landing page.

    One config per group (OneToOneField). Controls what appears in each fixed
    section of the public landing surface (Decision 1: Hero → Featured Content
    → About → Engagement → Footer). Groups configure content; they cannot change
    section order or layout pattern.

    is_active=True means the public landing page is live. False means the page
    is in preparation and not yet reachable.

    Featured content is backed by a Collection (Decision 4). If no collection is
    set, featured_item_ids provides an ordered fallback list of WritingPiece UUIDs.

    Subscription routes to the configured LanternmailList for this group (Decision 5).
    MB's list is distinct from the Crossroads community list.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    group = models.OneToOneField(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="public_config",
    )

    is_active = models.BooleanField(
        default=False,
        help_text="When True, the public landing page is reachable by anonymous visitors.",
    )

    # ---- Hero ----
    hero_eyebrow = models.CharField(
        max_length=200,
        blank=True,
        help_text='Orientation label, e.g. "Mindful Brilliance · Crossroads"',
    )
    hero_headline = models.CharField(
        max_length=500,
        blank=True,
        help_text="Point-of-view thesis — not a description",
    )
    hero_body = models.TextField(
        blank=True,
        help_text="2–3 sentences of context below the headline",
    )
    hero_primary_cta_label = models.CharField(max_length=100, blank=True)
    hero_primary_cta_action = models.CharField(
        max_length=500,
        blank=True,
        help_text="'scroll:subscribe' | 'scroll:featured' | external URL",
    )
    hero_secondary_cta_label = models.CharField(max_length=100, blank=True)
    hero_secondary_cta_action = models.CharField(
        max_length=500,
        blank=True,
        help_text="'scroll:subscribe' | 'scroll:featured' | external URL",
    )

    # ---- Featured Content ----
    featured_collection = models.ForeignKey(
        "curation.Collection",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_config_featured",
        help_text="Preferred source for featured content (Decision 4). Drives ordering and selection.",
    )
    featured_item_ids = ArrayField(
        models.UUIDField(),
        default=list,
        blank=True,
        help_text="Ordered fallback when no collection is set. WritingPiece UUIDs.",
    )
    featured_content_type = models.CharField(
        max_length=20,
        default="writing",
        choices=[("writing", "Writing"), ("documents", "Documents"), ("mixed", "Mixed")],
    )
    featured_layout = models.CharField(
        max_length=20,
        default="grid",
        choices=[("grid", "Grid"), ("list", "List")],
    )

    # ---- About ----
    about_text = models.TextField(blank=True, help_text="Short paragraph about the group")
    about_descriptors = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        help_text="Scannable descriptor list, e.g. ['System architecture', 'AI workflows']",
    )

    # ---- Engagement / Contact ----
    engagement_text = models.TextField(blank=True)
    engagement_capability_pills = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True,
    )
    engagement_cta_label = models.CharField(max_length=100, blank=True)
    engagement_cta_action = models.CharField(
        max_length=500,
        blank=True,
        help_text="'email:admin@example.com' | external URL | internal path",
    )

    # ---- Subscription ----
    subscription_list = models.ForeignKey(
        "lanternmail.LanternmailList",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="public_config_subscriptions",
        help_text="The mailing list public visitors subscribe to. MB list ≠ Crossroads list.",
    )

    # ---- Timestamps ----
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "groups"
        verbose_name = "Group Public Config"
        verbose_name_plural = "Group Public Configs"

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"GroupPublicConfig({self.group.slug}, {status})"
