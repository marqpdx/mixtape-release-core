# surfaces/services/argus_initiatives.py
#
# ADR-0064 D3: each Argus block gets its own Initiative, sponsored by the
# Argus Team, linked to the Argus Surface profile. D3 was amended 2026-11-09
# to name a real field, Initiative.block_slug (nullable, unique within its
# Surface) -- a title is a name, and D5 already says the Argus Team is found
# "by a fixed marker, never by its name"; the same principle holds here.
# This replaces the earlier title-convention lookup ("Argus: {block_slug}").

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

    initiative = Initiative.objects.filter(surface=profile, block_slug=block_slug).first()
    if initiative:
        return initiative

    initiative = Initiative.objects.create(
        title=f"Argus: {block_slug}",
        block_slug=block_slug,
        sponsor_content_type=group_ct,
        sponsor_object_id=team.id,
        surface=profile,
        status=InitiativeStatus.ACTIVE,
        created_by=site_owner,
    )
    InitiativeLog.objects.get_or_create(initiative=initiative)
    return initiative
