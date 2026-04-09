# groups/services/member_startup.py

"""
MemberStartupService — runs once when a new member joins the platform.

Idempotent: safe to call multiple times without duplicating records.
Atomic: all steps succeed or all roll back.

Two invitation paths:
  Path A — invited directly to Crossroads: membership already created by caller.
  Path B — invited to another group: Crossroads membership created here.

In both paths the service is called identically.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from groups.models import GroupMembership
from groups.models.group import Group
from initiatives.models import ApertureLog, Initiative, InitiativeStatus
from profiles.models import UserProfile

logger = logging.getLogger(__name__)


@dataclass
class MemberStartupResult:
    user_profile: UserProfile
    crossroads_membership: GroupMembership
    personal_initiative: Initiative
    aperture_log: ApertureLog
    was_new: bool


class MemberStartupService:
    """
    Canonical location for all initialization that must happen when a new
    member joins the platform.

    Steps (in order):
      1. Create UserProfile (if not exists)
      2. Add member to Crossroads (if not already a member)
      3. Create Personal Initiative (if not exists)
      4. Create ApertureLog for Personal Initiative (if not exists)
    """

    @staticmethod
    @transaction.atomic
    def run(user) -> MemberStartupResult:
        was_new = False

        # Step 1 — UserProfile
        profile, profile_created = UserProfile.objects.get_or_create(
            user=user,
            defaults={"display_name": user.username},
        )
        if profile_created:
            was_new = True

        # Step 2 — Crossroads membership
        crossroads_slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "crossroads")
        crossroads = Group.objects.get(slug=crossroads_slug)
        user_ct = ContentType.objects.get_for_model(user.__class__)
        membership, _ = GroupMembership.objects.get_or_create(
            group=crossroads,
            member_content_type=user_ct,
            member_object_id=user.id,
            defaults={
                "roles": ["member"],
                "is_active": True,
                "is_pending": False,
            },
        )

        # Step 3 — Personal Initiative
        initiative, initiative_created = Initiative.objects.get_or_create(
            sponsor_content_type=user_ct,
            sponsor_object_id=user.id,
            is_personal=True,
            defaults={
                "title": f"{user.username}'s Initiative",
                "status": InitiativeStatus.ACTIVE,
                "created_by": user,
                "parent": None,
            },
        )
        if initiative_created:
            was_new = True

        # Step 4 — ApertureLog
        aperture_log, _ = ApertureLog.objects.get_or_create(
            initiative=initiative,
        )

        return MemberStartupResult(
            user_profile=profile,
            crossroads_membership=membership,
            personal_initiative=initiative,
            aperture_log=aperture_log,
            was_new=was_new,
        )
