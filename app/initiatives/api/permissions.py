from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response

from livewire.permissions import HasOrchestrationWriteScope


__all__ = ["HasOrchestrationWriteScope", "get_initiative_for_log"]


def get_initiative_for_log(request, initiative_id):
    """Return (initiative, None) if the user is the sponsor (member ownership check), else (None, 404 response)."""
    from initiatives.models import Initiative

    initiative = get_object_or_404(Initiative, pk=initiative_id)
    user_ct = ContentType.objects.get_for_model(request.user.__class__)
    is_owner = (
        initiative.sponsor_content_type_id == user_ct.id
        and str(initiative.sponsor_object_id) == str(request.user.id)
    )
    if not is_owner and not request.user.is_superuser:
        return None, Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return initiative, None
