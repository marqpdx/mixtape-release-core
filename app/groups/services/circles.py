# groups/services/circles.py

"""
Service layer for Circle decorator operations.

CR-D: apply_working_circle_profile() and apply_deliverable_intent() services.
"""

from django.db import transaction

from groups.models.circle import CircleDeliverableIntent, DeliverableType
from groups.models.dec_enums import AssignmentSource, GroupType
from groups.models.decorators.assignments import GroupHasDecorator
from groups.models.decorators.catalog import GroupDecorator
from groups.models.decorators.profiles import GroupDecoratorProfile


class CircleDecoratorError(Exception):
    pass


def _require_circle(group):
    if group.group_type != GroupType.CIRCLE:
        raise CircleDecoratorError(
            f"Group '{group.slug}' is type '{group.group_type}', not 'circle'."
        )


def _ensure_group_has_decorator(group, decorator, *, source, source_profile=None, assigned_by=None):
    """
    Write a GroupHasDecorator row for (group, decorator). Idempotent.

    Returns (GroupHasDecorator, created).
    If the row already exists but is disabled, re-enables it.
    """
    link, created = GroupHasDecorator.objects.get_or_create(
        group=group,
        decorator=decorator,
        defaults={
            "enabled": True,
            "source": source,
            "source_profile": source_profile,
            "assigned_by": assigned_by,
        },
    )
    if not created and not link.enabled:
        link.enabled = True
        link.save(update_fields=["enabled", "modified_at"])
    return link, created


def _ensure_circle_deliverable_intent(circle, deliverable_type):
    """
    Write a CircleDeliverableIntent record for circle. Idempotent.

    Returns (CircleDeliverableIntent, created).
    Existing record is left unchanged (deliverable_type may have been updated by the user).
    """
    return CircleDeliverableIntent.objects.get_or_create(
        circle=circle,
        defaults={"deliverable_type": deliverable_type},
    )


@transaction.atomic
def apply_deliverable_intent(circle, deliverable_type, assigned_by=None):
    """
    Apply hasDeliverableIntent to a Circle directly (source=manual).

    Creates a GroupHasDecorator row for hasDeliverableIntent and a
    CircleDeliverableIntent record with the given deliverable_type.
    Idempotent — safe to call if already applied.

    Args:
        circle: Group instance (must be group_type='circle')
        deliverable_type: DeliverableType value (puddlejump_doc | dispatch | finding)
        assigned_by: User who is applying the decorator

    Returns:
        dict with keys 'decorator_link' and 'deliverable_intent'

    Raises:
        CircleDecoratorError: if the group is not a circle
        GroupDecorator.DoesNotExist: if hasDeliverableIntent is not in the catalog
    """
    _require_circle(circle)

    decorator = GroupDecorator.objects.get(code="hasDeliverableIntent")
    link, _ = _ensure_group_has_decorator(
        circle,
        decorator,
        source=AssignmentSource.MANUAL,
        assigned_by=assigned_by,
    )
    cdi, _ = _ensure_circle_deliverable_intent(circle, deliverable_type)

    return {"decorator_link": link, "deliverable_intent": cdi}


@transaction.atomic
def apply_working_circle_profile(circle, deliverable_type, assigned_by=None):
    """
    Apply the profile__WorkingCircle profile bundle to a Circle.

    Bundle-as-template: each decorator in the profile's GroupProfileItems is
    written as an independent GroupHasDecorator row (source=profile,
    source_profile=profile). The profile can be removed later without
    cascading those rows.

    When hasDeliverableIntent is in the bundle, a CircleDeliverableIntent
    record is also created with the given deliverable_type.

    Args:
        circle: Group instance (must be group_type='circle')
        deliverable_type: DeliverableType value — required because
            hasDeliverableIntent is in the bundle
        assigned_by: User who is applying the profile

    Returns:
        dict with keys:
          'profile'          — GroupDecoratorProfile
          'decorator_links'  — list of (GroupHasDecorator, created) tuples
          'deliverable_intent' — CircleDeliverableIntent or None

    Raises:
        CircleDecoratorError: if the group is not a circle
        GroupDecoratorProfile.DoesNotExist: if profile__WorkingCircle is missing
    """
    _require_circle(circle)

    profile = GroupDecoratorProfile.objects.get(code="profile__WorkingCircle")
    items = profile.items.select_related("decorator").all()

    decorator_links = []
    cdi = None

    for item in items:
        link, created = _ensure_group_has_decorator(
            circle,
            item.decorator,
            source=AssignmentSource.PROFILE,
            source_profile=profile,
            assigned_by=assigned_by,
        )
        decorator_links.append((link, created))

        if item.decorator.code == "hasDeliverableIntent":
            cdi, _ = _ensure_circle_deliverable_intent(circle, deliverable_type)

    return {
        "profile": profile,
        "decorator_links": decorator_links,
        "deliverable_intent": cdi,
    }
