from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils.text import slugify

from groups.models import (
    Group,
    GroupMembership,
    GroupPermissionProfile,
    GroupPermissionProfileItem,
    MembershipDecorator,
    MembershipHasDecorator,
)
from groups.permissions.decorators import MEMBERSHIP_DECORATORS


User = get_user_model()

CONTRIBUTOR_PROFILE_CODE = "contributor"
MODERATOR_PROFILE_CODE = "moderator"
STORYLINE_DECORATOR_CODE = "can__PostToStoryline"


def get_phase1_membership_decorators() -> dict[str, dict[str, str]]:
    decorators = dict(MEMBERSHIP_DECORATORS)
    decorators.setdefault(
        STORYLINE_DECORATOR_CODE,
        {
            "code": STORYLINE_DECORATOR_CODE,
            "name": "Post to Storyline",
            "description": "Create Storyline posts in this group.",
            "category": "capability",
        },
    )
    return decorators


def ensure_membership_decorator_catalog() -> dict[str, MembershipDecorator]:
    decorator_map: dict[str, MembershipDecorator] = {}
    for code, meta in get_phase1_membership_decorators().items():
        decorator, _ = MembershipDecorator.objects.get_or_create(
            code=code,
            defaults={
                "label": meta["name"],
                "description": meta["description"],
                "category": meta["category"],
            },
        )
        decorator_map[code] = decorator
    return decorator_map


@transaction.atomic
def seed_group_permission_profiles(group: Group) -> dict[str, GroupPermissionProfile]:
    decorators = ensure_membership_decorator_catalog()

    contributor, _ = GroupPermissionProfile.objects.get_or_create(
        group=group,
        code=CONTRIBUTOR_PROFILE_CODE,
        defaults={
            "name": "Contributor",
            "description": "Standard member profile for Storyline participation.",
            "is_default": True,
            "sort_order": 0,
        },
    )
    moderator, _ = GroupPermissionProfile.objects.get_or_create(
        group=group,
        code=MODERATOR_PROFILE_CODE,
        defaults={
            "name": "Moderator",
            "description": "Elevated member profile for moderation and management.",
            "is_default": False,
            "sort_order": 1,
        },
    )

    contributor_codes = [STORYLINE_DECORATOR_CODE]
    moderator_codes = list(decorators.keys())

    _replace_profile_decorators(contributor, contributor_codes, decorators)
    _replace_profile_decorators(moderator, moderator_codes, decorators)

    if not GroupPermissionProfile.objects.filter(
        group=group,
        is_default=True,
    ).exists():
        contributor.is_default = True
        contributor.save(update_fields=["is_default"])

    return {
        CONTRIBUTOR_PROFILE_CODE: contributor,
        MODERATOR_PROFILE_CODE: moderator,
    }


def _replace_profile_decorators(
    profile: GroupPermissionProfile,
    decorator_codes: list[str],
    decorators: dict[str, MembershipDecorator],
) -> None:
    GroupPermissionProfileItem.objects.filter(profile=profile).exclude(
        decorator__code__in=decorator_codes
    ).delete()

    for index, code in enumerate(decorator_codes):
        GroupPermissionProfileItem.objects.update_or_create(
            profile=profile,
            decorator=decorators[code],
            defaults={"sort_order": index},
        )


def _generate_unique_profile_code(group: Group, name: str) -> str:
    base_code = slugify(name).strip("-") or "profile"
    code = base_code
    suffix = 2
    while GroupPermissionProfile.objects.filter(group=group, code=code).exists():
        code = f"{base_code}-{suffix}"
        suffix += 1
    return code


def get_default_permission_profile(group: Group) -> GroupPermissionProfile:
    profile = GroupPermissionProfile.objects.filter(
        group=group,
        is_default=True,
    ).first()
    if profile:
        return profile
    return seed_group_permission_profiles(group)[CONTRIBUTOR_PROFILE_CODE]


@transaction.atomic
def set_default_permission_profile(profile: GroupPermissionProfile) -> GroupPermissionProfile:
    GroupPermissionProfile.objects.filter(group=profile.group, is_default=True).exclude(
        id=profile.id
    ).update(is_default=False)

    if not profile.is_default:
        profile.is_default = True
        profile.save(update_fields=["is_default"])

    return profile


@transaction.atomic
def sync_memberships_for_profile(
    profile: GroupPermissionProfile,
    *,
    assigned_by=None,
) -> None:
    memberships = GroupMembership.objects.filter(permission_profile=profile).select_related("group")
    for membership in memberships.iterator():
        assign_permission_profile_to_membership(
            membership,
            profile,
            assigned_by=assigned_by,
        )


@transaction.atomic
def create_permission_profile(
    group: Group,
    *,
    name: str,
    description: str = "",
    decorator_codes: list[str] | None = None,
    is_default: bool = False,
) -> GroupPermissionProfile:
    decorator_codes = decorator_codes or []
    decorators = ensure_membership_decorator_catalog()

    profile = GroupPermissionProfile.objects.create(
        group=group,
        code=_generate_unique_profile_code(group, name),
        name=name,
        description=description,
        is_default=False,
        sort_order=GroupPermissionProfile.objects.filter(group=group).count(),
    )

    _replace_profile_decorators(profile, decorator_codes, decorators)

    if is_default:
        set_default_permission_profile(profile)

    return profile


@transaction.atomic
def update_permission_profile(
    profile: GroupPermissionProfile,
    *,
    name: str,
    description: str = "",
    decorator_codes: list[str] | None = None,
    assigned_by=None,
) -> GroupPermissionProfile:
    decorator_codes = decorator_codes or []
    decorators = ensure_membership_decorator_catalog()

    profile.name = name
    profile.description = description
    profile.save(update_fields=["name", "description"])

    _replace_profile_decorators(profile, decorator_codes, decorators)
    sync_memberships_for_profile(profile, assigned_by=assigned_by)
    return profile


@transaction.atomic
def clone_permission_profile(
    profile: GroupPermissionProfile,
    *,
    name: str | None = None,
) -> GroupPermissionProfile:
    decorators = list(
        profile.items.select_related("decorator").values_list("decorator__code", flat=True)
    )
    return create_permission_profile(
        profile.group,
        name=name or f"{profile.name} Copy",
        description=profile.description,
        decorator_codes=decorators,
        is_default=False,
    )


@transaction.atomic
def assign_permission_profile_to_membership(
    membership: GroupMembership,
    profile: GroupPermissionProfile | None,
    *,
    assigned_by=None,
) -> GroupMembership:
    if profile and profile.group_id != membership.group_id:
        raise ValueError("Permission profile must belong to the same group as the membership")

    membership.permission_profile = profile
    membership.save(update_fields=["permission_profile"])

    desired_codes = set()
    if profile:
        desired_codes = set(
            profile.items.select_related("decorator").values_list("decorator__code", flat=True)
        )

    existing_profile_links = MembershipHasDecorator.objects.filter(
        membership=membership,
        source="profile",
    ).select_related("decorator")

    for link in existing_profile_links:
        if link.decorator.code not in desired_codes:
            link.delete()

    decorator_catalog = ensure_membership_decorator_catalog()
    for code in desired_codes:
        MembershipHasDecorator.objects.update_or_create(
            membership=membership,
            decorator=decorator_catalog[code],
            defaults={
                "enabled": True,
                "source": "profile",
                "source_profile": None,
                "source_group_permission_profile": profile,
                "assigned_by": assigned_by,
            },
        )

    return membership


def assign_default_permission_profile(
    membership: GroupMembership,
    *,
    assigned_by=None,
) -> GroupMembership:
    profile = get_default_permission_profile(membership.group)
    return assign_permission_profile_to_membership(
        membership,
        profile,
        assigned_by=assigned_by,
    )


@transaction.atomic
def backfill_existing_group_memberships() -> None:
    user_ct = ContentType.objects.get_for_model(User)
    for group in Group.objects.all().iterator():
        profiles = seed_group_permission_profiles(group)
        contributor = profiles[CONTRIBUTOR_PROFILE_CODE]
        memberships = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
        )
        for membership in memberships.iterator():
            if membership.permission_profile_id:
                continue
            assign_permission_profile_to_membership(membership, contributor)
