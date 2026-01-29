# activity/seed_activity_types.py

from activity.models import ActivityType


CANONICAL = [
    dict(code="group.post.created", title="New Post in Group", default_channel="activity", default_priority="normal", suppressible_by_user=True),
    dict(code="post.comment.created", title="New Comment on Post", default_channel="activity", default_priority="normal", suppressible_by_user=True),
    dict(code="group.announcement",  title="Group Announcement",   default_channel="activity", default_priority="normal", suppressible_by_user=True),
    dict(code="chat.mention",        title="Chat Mention",         default_channel="messages", default_priority="critical", suppressible_by_user=False),
]

def run():
    for row in CANONICAL:
        ActivityType.objects.get_or_create(
            code=row["code"],
            defaults=dict(
                title=row["title"],
                summary="",
                default_channel=row["default_channel"],
                default_priority=row["default_priority"],
                suppressible_by_user=row["suppressible_by_user"],
            ),
        )
