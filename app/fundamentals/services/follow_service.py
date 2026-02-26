# fundamentals/services/follow_service.py

from django.db import transaction
from django.utils import timezone

from fundamentals.models import Follow


class FollowError(Exception):
    pass


@transaction.atomic
def follow_user(*, follower, target):
    """Create a follow relationship. Idempotent."""
    if follower.id == target.id:
        raise FollowError("Cannot follow yourself.")

    follow, created = Follow.objects.get_or_create(
        follower=follower,
        following=target,
    )
    return follow, created


@transaction.atomic
def unfollow_user(*, follower, target):
    """Remove a follow relationship via soft delete."""
    deleted_count, _ = Follow.objects.filter(
        follower=follower,
        following=target,
        deleted_at__isnull=True,
    ).update(deleted_at=timezone.now())
    return deleted_count > 0


def get_following_ids(user):
    """Return list of user IDs the user follows (for Streams query)."""
    return list(
        Follow.objects.filter(
            follower=user,
            deleted_at__isnull=True,
        ).values_list("following_id", flat=True)
    )


def get_followers_count(user):
    return Follow.objects.filter(following=user, deleted_at__isnull=True).count()


def get_following_count(user):
    return Follow.objects.filter(follower=user, deleted_at__isnull=True).count()


def is_following(*, follower, target):
    return Follow.objects.filter(
        follower=follower, following=target, deleted_at__isnull=True,
    ).exists()
