# surfaces/services/argus_initiatives.py
#
# ADR-0064 D3: each Argus block gets its own Initiative, sponsored by the
# Argus Team, linked to the Argus Surface profile.
#
# D3's text names `seed_context` as where "the block's id and settings"
# would live, but that field already carries a different, established
# meaning in the current model ("Snapshot of the source Initiative's
# rolling_summary at fork time" -- initiatives.models.Initiative.
# seed_context). Overloading it would collide with existing fork support,
# so this looks a block's Initiative up by a title convention instead
# ("Argus: {block_slug}", unique in practice because only this function
# ever creates one) and flags the discrepancy here rather than deciding
# the ADR's wording silently: Puddlejump/the CTO may want D3 amended to
# name a real field, or a new one added, instead.

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType

from groups.models import Group
from initiatives.models import Initiative, InitiativeLog, InitiativeStatus
from surfaces.models import SurfaceProfile
from surfaces.services.argus_team import ensure_argus_team


def ensure_block_initiative(block_slug: str, *, site_owner) -> Initiative:
    team = ensure_argus_team(site_owner=site_owner)
    profile = SurfaceProfile.objects.get(slug="argus")
    group_ct = ContentType.objects.get_for_model(Group)
    title = f"Argus: {block_slug}"

    initiative = Initiative.objects.filter(
        sponsor_content_type=group_ct,
        sponsor_object_id=team.id,
        title=title,
    ).first()
    if initiative:
        return initiative

    initiative = Initiative.objects.create(
        title=title,
        sponsor_content_type=group_ct,
        sponsor_object_id=team.id,
        surface=profile,
        status=InitiativeStatus.ACTIVE,
        created_by=site_owner,
    )
    InitiativeLog.objects.get_or_create(initiative=initiative)
    return initiative
