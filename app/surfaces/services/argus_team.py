# surfaces/services/argus_team.py
#
# ADR-0064 D5: the Argus Team is a system-designated Group, created at
# install or later by an idempotent command, found by a fixed marker (never
# by its name) -- private and invitation-only, with no public page or tenant
# subdomain. The site owner is always its first member. It sponsors Argus's
# Initiatives; runs go on the account of the builder who starts them (D8),
# so membership here never grants a shared login.
#
# The fixed marker is a deterministic UUID (same pattern as
# mixtape.services.defaults.ensure_default_group): lookup is by id, not by
# slug or title, so renaming the Group's display title can never create a
# second one or lose track of the original.

import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from groups.models import Group, GroupMembership
from groups.models.dec_enums import AdmissionPolicy, GroupType, GroupVisibility
from groups.models.types import CommunityGroup
from groups.services.permission_profiles import (
    MODERATOR_PROFILE_CODE,
    assign_permission_profile_to_membership,
    seed_group_permission_profiles,
)

ARGUS_TEAM_SLUG = "argus-team"
ARGUS_TEAM_UUID_NAMESPACE = "mixtape://argus-team"


def _det_uuid(namespace: str, key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}#{key}")


def argus_team_id() -> uuid.UUID:
    """The Argus Team's fixed marker. Stable across renames; never derived from title."""
    return _det_uuid(ARGUS_TEAM_UUID_NAMESPACE, ARGUS_TEAM_SLUG)


def get_argus_team() -> Group | None:
    return Group.objects.filter(id=argus_team_id()).first()


def ensure_argus_team(*, site_owner) -> Group:
    """Idempotently ensure the Argus Team exists, with site_owner as its first member."""
    group = get_argus_team()
    if group:
        return group

    group = Group(
        id=argus_team_id(),
        title="Argus Team",
        slug=ARGUS_TEAM_SLUG,
        slug_is_custom=True,
        group_type=GroupType.COMMUNITY,
        visibility=GroupVisibility.PRIVATE,
        admission_policy=AdmissionPolicy.INVITE_ONLY,
        is_active=True,
        # No public page or tenant subdomain (D5): never opted into either.
        in_crossroads_directory=False,
        catalyst_enabled=False,
    )
    group.set_sponsor(site_owner)
    group.set_submitted_by(site_owner)
    group.author = site_owner
    group.author_name = site_owner.get_full_name() or site_owner.username
    group.save()

    CommunityGroup.objects.create(
        group=group,
        tagline="Builders who tend Mixtape's own quality and fidelity",
    )

    user_content_type = ContentType.objects.get_for_model(get_user_model())
    membership = GroupMembership.objects.create(
        group=group,
        member_content_type=user_content_type,
        member_object_id=site_owner.pk,
        roles=["member", "admin", "owner"],
        is_active=True,
        is_pending=False,
    )
    profiles = seed_group_permission_profiles(group)
    assign_permission_profile_to_membership(
        membership, profiles[MODERATOR_PROFILE_CODE], assigned_by=site_owner,
    )

    return group
