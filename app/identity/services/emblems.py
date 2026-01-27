# apps/identity/services/emblems.py

from identity.models import EmblemAvatar, EmblemAvatarType


def ensure_default_user_avatar(user_profile):
    """Create a default avatar for a user profile if none exists"""
    print("ensure_default_user_avatar", user_profile, user_profile.avatar_id)

    if user_profile.avatar_id:
        return user_profile.avatar

    # Changed from "dicebear:initials" to "initials:rounded"
    t = EmblemAvatarType.objects.get(engine="initials", style="rounded")

    # Get initials from user's name
    user = user_profile.user
    first = user.first_name[:1].upper() if user.first_name else ""
    last = user.last_name[:1].upper() if user.last_name else ""
    initials = (first + last) or user.username[:2].upper()

    emblem = EmblemAvatar(
        type=t,
        seed=initials.lower(),
        initials=initials,
        fg="#FFFFFF",
        bg="#2F855A"  # Green
    )
    emblem.set_sponsor(user)
    emblem.save()

    user_profile.avatar = emblem
    user_profile.save(update_fields=["avatar"])

    return emblem


def ensure_default_group_emblem(group):
    """Create a default emblem for a group if none exists"""
    print("ensure_default_group_emblem", group, group.emblem_id)

    if group.emblem_id:
        return group.emblem

    # Changed from "boring:beam" to "dicebear:shapes"
    t = EmblemAvatarType.objects.get(engine="dicebear", style="shapes")

    emblem = EmblemAvatar(
        type=t,
        seed=str(group.id),
        palette=[]
    )
    emblem.set_sponsor(group)
    emblem.save()

    group.emblem = emblem
    group.save(update_fields=["emblem"])

    return emblem