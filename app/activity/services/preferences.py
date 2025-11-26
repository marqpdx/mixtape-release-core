# activity/services/preferences.py
"""
Notification Preferences Service

Applies user notification preferences to determine delivery method and priority.
Supports per-bucket and per-activity-code preferences.
"""

from typing import Tuple
from activity.models import NotificationPreference


def apply_preferences(user, action) -> Tuple[str, str, str]:
    """
    Apply user notification preferences to an action.

    Returns: (level, bucket, priority)
        - level: "mute" | "digest" | "realtime"
        - bucket: action.channel or user-overridden
        - priority: action.priority or user-overridden

    Preference hierarchy:
    1. activity_code-specific preference (most specific)
    2. bucket-level preference
    3. defaults (realtime)

    Args:
        user: User object to check preferences for
        action: Action object to apply preferences to

    Returns:
        Tuple of (level, bucket, priority)
    """
    # Check activity_code-specific preference first (most specific)
    pref = NotificationPreference.objects.filter(
        user=user,
        activity_code=action.activity_code
    ).first()

    if not pref:
        # Fall back to bucket-level preference
        pref = NotificationPreference.objects.filter(
            user=user,
            bucket=action.channel
        ).first()

    # Determine notification level
    if pref:
        level = pref.level
    else:
        # Default: realtime for all
        level = "realtime"

    # Check if ActivityType has suppressible_by_user=False (override mute)
    if action.activity_type and not action.activity_type.suppressible_by_user:
        # User cannot suppress this type (e.g., critical mentions)
        if level == "mute":
            level = "realtime"  # Force to realtime

    # Bucket and priority come from action (user can't override these currently)
    bucket = action.channel
    priority = action.priority

    return level, bucket, priority


def get_user_preference(user, bucket=None, activity_code=None):
    """
    Get a user's notification preference for a bucket or activity code.

    Args:
        user: User object
        bucket: Optional bucket name (messages, activity, system)
        activity_code: Optional activity code (chat.mention, post.created, etc.)

    Returns:
        NotificationPreference object or None
    """
    if activity_code:
        return NotificationPreference.objects.filter(
            user=user,
            activity_code=activity_code
        ).first()
    elif bucket:
        return NotificationPreference.objects.filter(
            user=user,
            bucket=bucket
        ).first()
    return None


def set_user_preference(user, level: str, bucket=None, activity_code=None):
    """
    Set a user's notification preference.

    Args:
        user: User object
        level: "mute" | "digest" | "realtime"
        bucket: Optional bucket name
        activity_code: Optional activity code

    Returns:
        NotificationPreference object
    """
    if not bucket and not activity_code:
        raise ValueError("Must specify either bucket or activity_code")

    pref, created = NotificationPreference.objects.update_or_create(
        user=user,
        bucket=bucket,
        activity_code=activity_code,
        defaults={"level": level}
    )
    return pref
