# mindmap/services/mindmap_service.py

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F

from mindmap.models import MindMap


@transaction.atomic
def create_mindmap(*, sponsor, title="Untitled", author=None, submitted_by=None):
    """
    Create a new MindMap with polymorphic sponsor.
    sponsor: a model instance (User or Group).
    """
    mindmap = MindMap(title=title)
    mindmap.set_sponsor(sponsor)
    if author:
        mindmap.author = author
    if submitted_by:
        mindmap.submitted_by = submitted_by
    mindmap.save()
    return mindmap


def update_mindmap(*, mindmap, **fields):
    """
    PATCH allowed fields on a mindmap.
    Does not bump version (viewport, title, status, share_mode are non-structural).
    """
    allowed = {"title", "viewport", "status", "share_mode", "share_token", "summary"}
    update_fields = []
    for key, val in fields.items():
        if key in allowed:
            setattr(mindmap, key, val)
            update_fields.append(key)
    if update_fields:
        update_fields.append("updated_at")
        mindmap.save(update_fields=update_fields)
    return mindmap


def bump_version(mindmap):
    """Atomically increment version using F expression."""
    MindMap.objects.filter(pk=mindmap.pk).update(version=F("version") + 1)
    mindmap.refresh_from_db(fields=["version"])
    return mindmap.version
