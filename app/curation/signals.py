# curation/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="groups.Group")
def create_core_resources_collection(sender, instance, created, **kwargs):
    if not created:
        return
    from django.contrib.contenttypes.models import ContentType
    from curation.models import Collection

    group_ct = ContentType.objects.get_for_model(instance)
    Collection.objects.get_or_create(
        title="Core Resources",
        sponsor_content_type=group_ct,
        sponsor_object_id=instance.id,
        defaults={
            "visibility": "members",
            "scope": "general",
        },
    )
