# activity/signals.py (continued)

from django.dispatch import receiver

from django.db.models.signals import post_save
from activity.models import ActionOutbox
from activity.tasks import fanout_action_task

@receiver(post_save, sender=ActionOutbox)
def _outbox_created(sender, instance: ActionOutbox, created: bool, **kwargs):
    if created:
        fanout_action_task.delay(str(instance.action_id))






# (optional: bind to Django signals)

# Use if you want automatic producers on post_save of your domain models.
# If you prefer explicit calls from service code, you can skip this.

# activity/signals.py
# from django.db.models.signals import post_save
# from django.dispatch import receiver

# from posts.models import Post, Comment  # adjust paths
# from groups.models import GroupAnnouncement  # adjust
# from activity import producers

# @receiver(post_save, sender=Post)
# def _post_created_signal(sender, instance: Post, created: bool, **kwargs):
#     if created:
#         groups = list(instance.groups.all())  # however you relate posts to groups
#         if groups:
#             producers.on_group_post_created(post=instance, groups=groups, actor_user=instance.author)

# @receiver(post_save, sender=Comment)
# def _comment_created_signal(sender, instance: Comment, created: bool, **kwargs):
#     if created:
#         producers.on_comment_created(comment=instance, post=instance.post)

# @receiver(post_save, sender=GroupAnnouncement)
# def _group_announcement_signal(sender, instance: GroupAnnouncement, created: bool, **kwargs):
#     if created:
#         producers.on_group_announcement(group=instance.group, announcement=instance)
