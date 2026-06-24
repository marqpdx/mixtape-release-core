# tapestry/models.py
#
# Minimal Place stub — CM-0 (commons-adr.md D17). Tapestry has been
# referenced as an existing subsystem in canon since stackroom-extraction-adr
# (2026-04-03) but had no code until this. Scoped to exactly what Commons
# (ADR-0049) needs to anchor a Leaf. Full Tapestry (search, map rendering,
# place merge/dedup, multi-source data) is out of scope here — deferred to
# its own future ADR/build plan.
import uuid

from django.db import models

from fundamentals.bases import BaseModel


class Place(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    address = models.CharField(max_length=500, blank=True, default="")

    class Meta(BaseModel.Meta):
        ordering = ["name"]

    def __str__(self):
        return self.name
