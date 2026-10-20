# shuttle/models.py
#
# IdeaTuple — the Idea-tuple holder for Stories Not Yet Told (ADR-0058
# D8, SH-9). "The agent may offer two or three top-tier finds per weave,
# as one question. One yes stores them on the weave's Idea tuple;
# ignored, they are gone. Matching is faceted: a search on any one Idea
# returns every tuple containing it, and adding Ideas narrows the
# results. A find becomes a published node only when a person brings a
# story to it in a later weave. The tuple holder is the one genuinely
# new model." Per the SH-7a contract's result_out fixture, one
# IdeaTuple is written per offer in packet_out.stories_not_yet_told.offers
# when the person answers yes — not one tuple per weave holding every
# offer, since each offer is itself the tuple of Ideas that facet it.
import uuid

from django.conf import settings
from django.db import models

from fundamentals.bases import BaseModel


class IdeaTuple(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    label = models.CharField(
        max_length=255,
        help_text="The offer's display wording, as shown in the packet's stories_not_yet_told.",
    )
    ideas = models.ManyToManyField(
        "classifications.Tag",
        related_name="idea_tuples",
        limit_choices_to={"is_idea": True},
        help_text="The Ideas this find is faceted by (D8). Narrows on search as more are added.",
    )
    action_run = models.ForeignKey(
        "initiatives.ActionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="idea_tuples",
        help_text="The weave that offered this find.",
    )
    source_offer_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="The packet-local stories_not_yet_told offer id, for client-side reconciliation.",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="idea_tuples",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return self.label
