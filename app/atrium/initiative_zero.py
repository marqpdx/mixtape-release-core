# atrium/initiative_zero.py
"""
Initiative Zero (I0): every member's default Initiative, where personal Dialogues
live (CTO, 2026-11-04; design-st3b §13). It is the Personal Initiative that
MemberStartupService makes (sponsor = the User, is_personal=True); people see a
plain label, I0 is the internal term.
"""


def initiative_zero(user):
    """The member's I0, made (as MemberStartupService step 3–4 makes it) if it is missing."""
    from django.contrib.contenttypes.models import ContentType

    from initiatives.models import Initiative, InitiativeLog, InitiativeStatus

    initiative, _ = Initiative.objects.get_or_create(
        sponsor_content_type=ContentType.objects.get_for_model(type(user)),
        sponsor_object_id=user.pk,
        is_personal=True,
        deleted_at__isnull=True,
        defaults={
            "title": f"{user.username}'s Initiative",
            "status": InitiativeStatus.ACTIVE,
            "created_by": user,
            "parent": None,
        },
    )
    InitiativeLog.objects.get_or_create(initiative=initiative)
    return initiative
