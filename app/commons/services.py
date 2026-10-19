# commons/services.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import CommonsItem


User = get_user_model()


@transaction.atomic
def capture_item(user, source_url="", title="", why_recommended="", sponsor=None):
    """
    Create a new CommonsItem. It exists once captured (D5) -- no curation
    pipeline or approval gate. Sponsor defaults to the submitting user if
    not provided.
    """
    if sponsor is None:
        sponsor = user

    item = CommonsItem()
    item.title = title or source_url
    item.source_url = source_url
    item.why_recommended = why_recommended
    item.recommended_by = user
    item.submitted_by = user
    item.author = user
    item.set_sponsor(sponsor)
    item.published_at = timezone.now()
    item.save()
    return item


FILAMENT_VERB_SLUG_MAP = {
    "founded_by": "founded-by",
    "located_in": "located-in",
    "collaborates_with": "collaborates-with",
    "teaches_at": "teaches-at",
    "inspired_by": "inspired-by",
    "affiliated_with": "affiliated-with",
    "program_of": "program-of",
}


@transaction.atomic
def create_filament(source, target, relation_type, note="", created_by=None):
    """Create a commons-domain Relationship between two CommonsItems."""
    from relations.service import RelationshipService
    slug = FILAMENT_VERB_SLUG_MAP.get(relation_type, relation_type)
    return RelationshipService.create_relationship(
        type_slug=slug,
        source=source,
        target=target,
        created_by=created_by,
        notes=note,
    )
