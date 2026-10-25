"""Personal Folio scope; group-sponsored records await the group access surface."""
from django.contrib.contenttypes.models import ContentType
from folio.models import Folio


def member_folios(user):
    return Folio.objects.filter(
        sponsor_content_type=ContentType.objects.get_for_model(user),
        sponsor_object_id=user.pk,
    )
