# activity/seed_activity_types.py

from activity.models import ActivityType


CANONICAL = [
    dict(code="group.post.created",            title="New Post in Group",          default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="post.comment.created",          title="New Comment on Post",        default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="group.announcement",            title="Group Announcement",         default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="chat.mention",                  title="Chat Mention",               default_channel="messages", default_priority="critical", suppressible_by_user=False),
    dict(code="group.threadworks.post_created",title="New Discussion Post",        default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="group.earthlab.course_updated", title="Course or Lesson Updated",   default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="group.livewire.message",        title="Group Chat Message",         default_channel="activity", default_priority="low",      suppressible_by_user=True),
    # Members
    dict(code="group.member.joined",           title="Member Joined Group",        default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="group.member.profile_updated",  title="Member Updated Profile",     default_channel="activity", default_priority="low",      suppressible_by_user=True),
    # Collections
    dict(code="group.collection.item_added",   title="Item Added to Collection",   default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="group.collection.updated",      title="Collection Updated",         default_channel="activity", default_priority="low",      suppressible_by_user=True),
    # Almanac
    dict(code="group.almanac.event_published", title="New Event Published",        default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    dict(code="group.almanac.occurrence_updated", title="Event Time Updated",      default_channel="activity", default_priority="normal",   suppressible_by_user=True),
    # Circle bubble-up (context = parent group, audience = circle members only)
    dict(code="group.circle.active",           title="Circle Activity",            default_channel="activity", default_priority="low",      suppressible_by_user=True),
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
