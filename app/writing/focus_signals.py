# writing/focus_signals.py
# Focus-Centered Writing ADR, §8: "Focus object deleted (issue removed) ->
# Focus marked abandoned, drops out of 'in progress.'" A GenericForeignKey
# has no DB-level cascade, so a real hook is needed or a deleted Issue would
# leave its Focus silently pointing at nothing.

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from writing.models import Focus, Issue


@receiver(post_delete, sender=Issue)
def issue_post_delete_abandons_focuses(sender, instance, **kwargs):
    issue_ct = ContentType.objects.get_for_model(Issue)
    Focus.objects.filter(
        target_content_type=issue_ct,
        target_object_id=instance.id,
        status=Focus.Status.ACTIVE,
    ).update(status=Focus.Status.ABANDONED, resolved_at=timezone.now())
