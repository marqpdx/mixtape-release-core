# activity/services/mentions.py



from users.models import CustomUser


def expand_mention_to_users(mention) -> list[CustomUser]:
    """
    Returns concrete User instances for a single MessageMention row.
    Supports mentionee = User or Group (via your GroupMembership model).
    """
    obj = mention.mentionee
    if obj is None:
        return []

    # User mention
    if isinstance(obj, CustomUser):
        return [obj]

    # Group mention (adjust import/path to your app)
    try:
        from groups.models import GroupMembership
        # Visibility checks could go here (private groups, roles, etc.)
        return [gm.user for gm in GroupMembership.objects.filter(group_id=obj.pk).select_related("user")]
    except Exception:
        # Unknown mentionee type → ignore for now
        return []
