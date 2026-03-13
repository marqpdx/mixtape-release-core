# commons/services.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import CommonsItem, Filament


User = get_user_model()

# Curation status state machine: valid transitions
VALID_TRANSITIONS = {
    CommonsItem.CurationStatus.CAPTURED: [
        CommonsItem.CurationStatus.IN_CURATION,
        CommonsItem.CurationStatus.REJECTED,
    ],
    CommonsItem.CurationStatus.IN_CURATION: [
        CommonsItem.CurationStatus.READY,
        CommonsItem.CurationStatus.CAPTURED,  # send back
        CommonsItem.CurationStatus.REJECTED,
    ],
    CommonsItem.CurationStatus.READY: [
        CommonsItem.CurationStatus.APPROVED,
        CommonsItem.CurationStatus.IN_CURATION,  # send back
        CommonsItem.CurationStatus.REJECTED,
    ],
    CommonsItem.CurationStatus.APPROVED: [
        CommonsItem.CurationStatus.PUBLISHED,
        CommonsItem.CurationStatus.READY,  # send back
        CommonsItem.CurationStatus.REJECTED,
    ],
    CommonsItem.CurationStatus.PUBLISHED: [
        CommonsItem.CurationStatus.APPROVED,  # unpublish
    ],
    CommonsItem.CurationStatus.REJECTED: [
        CommonsItem.CurationStatus.CAPTURED,  # re-open
    ],
}


@transaction.atomic
def capture_item(user, source_url="", title="", why_recommended="", sponsor=None):
    """
    Create a new CommonsItem in 'captured' status.
    Sponsor defaults to the submitting user if not provided.
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
    item.curation_status = CommonsItem.CurationStatus.CAPTURED
    item.save()
    return item


@transaction.atomic
def advance_status(item, user, target_status):
    """
    Advance (or transition) curation status with validation.
    Returns the updated item.
    """
    current = item.curation_status
    valid_targets = VALID_TRANSITIONS.get(current, [])

    if target_status not in valid_targets:
        raise ValueError(
            f"Cannot transition from '{current}' to '{target_status}'. "
            f"Valid targets: {[s.value for s in valid_targets]}"
        )

    item.curation_status = target_status

    # Track who performed curation actions
    if target_status == CommonsItem.CurationStatus.IN_CURATION:
        item.curated_by = user
    elif target_status == CommonsItem.CurationStatus.APPROVED:
        item.approved_by = user
    elif target_status == CommonsItem.CurationStatus.PUBLISHED:
        item.published_at = timezone.now()

    item.save()
    return item


@transaction.atomic
def reject_item(item, user, reason=""):
    """Reject a CommonsItem from any pre-published status."""
    return advance_status(item, user, CommonsItem.CurationStatus.REJECTED)


@transaction.atomic
def create_filament(source, target, relation_type, note=""):
    """Create a relationship between two CommonsItems."""
    return Filament.objects.create(
        source=source,
        target=target,
        relation_type=relation_type,
        note=note,
    )
