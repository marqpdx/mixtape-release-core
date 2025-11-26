# apps/core/services/defaults.py
import uuid
from django.conf import settings
from django.template.defaultfilters import slugify
from django.contrib.contenttypes.models import ContentType
from groups.models import Group
from groups.models.group import GroupType
from groups.models.types import CommunityGroup

def _det_uuid(namespace: str, key: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}#{key}")


def ensure_default_group(*, sponsor_user) -> Group:
    """
    Idempotently ensure the Default Group exists and is sponsored by sponsor_user.
    Uses polymorphic sponsorship pattern via BaseContent.
    """
    name = getattr(settings, "MIXTAPE_DEFAULT_GROUP_NAME", "Crossroads")
    slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "") or slugify(name) or "crossroads"
    ns   = getattr(settings, "MIXTAPE_DEFAULT_GROUP_UUID_NAMESPACE", "mixtape://default-group")

    # Try by slug first (portable), then by our deterministic UUID
    group = Group.objects.filter(slug=slug).first()
    if group:
        return group

    gid = _det_uuid(ns, slug)
    group = Group.objects.filter(id=gid).first()
    if group:
        return group

    # Create new group with polymorphic sponsor
    group = Group(
        id=gid,
        title=name,
        slug=slug,
        is_active=True,
        group_type=GroupType.COMMUNITY
    )

    # Set sponsor BEFORE first save to satisfy NOT NULL constraints
    group.set_sponsor(sponsor_user)
    group.set_submitted_by(sponsor_user)

    # Set author fields (sponsor_user is both sponsor and author)
    group.author = sponsor_user
    group.author_name = sponsor_user.get_full_name() or sponsor_user.username

    group.save()

    CommunityGroup.objects.create(
        group=group,
        tagline="The default community for all users"
    )

    return group


def get_default_group():
    """
    Return the Default Group if it exists, else None.
    (Bootstrap is responsible for creation.)
    """
    from django.conf import settings
    from django.template.defaultfilters import slugify

    name = getattr(settings, "MIXTAPE_DEFAULT_GROUP_NAME", "Crossroads")
    slug = getattr(settings, "MIXTAPE_DEFAULT_GROUP_SLUG", "") or slugify(name) or "crossroads"

    return Group.objects.filter(slug=slug).first()
