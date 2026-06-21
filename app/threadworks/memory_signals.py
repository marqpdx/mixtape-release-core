# threadworks/memory_signals.py
#
# Memory-value signal handlers for Discussion and FeedPost (D6, D9, D10, D11).
# Weight constants are initial values; adjust post-launch via weight tuning pass.

from django.db.models import F
from django.db.models.signals import post_save
from django.dispatch import receiver

from threadworks.models import (
    Discussion,
    FeedPost,
    MemoryValueEvent,
    Post,
    PostReaction,
)

# Weight constants — intentionally declared here for easy tuning (ADR-0047 §12)
REACTION_WEIGHT = 0.5
REPLY_WEIGHT = 2.0
QUOTED_REPLY_BONUS = 1.5       # added on top of REPLY_WEIGHT when quoted_post is set
AUTHOR_REPLY_BONUS = 2.0       # added on top of REPLY_WEIGHT when author-distinguished
CREATION_SIGNAL_WEIGHTS = {'low': 1.0, 'medium': 3.0, 'high': 5.0}
SUMMARY_APPROVED_WEIGHT = 10.0

MEMORY_VALUE_WORKTABLE_THRESHOLD = 15.0
BERYL_TRIGGER_POST_INTERVAL = 10


def _log_event_and_update_score(container, event_type, delta, actor=None, notes=''):
    """Create a MemoryValueEvent and atomically increment the container's score."""
    from django.contrib.contenttypes.models import ContentType
    ct = ContentType.objects.get_for_model(container)
    MemoryValueEvent.objects.create(
        content_type=ct,
        object_id=container.pk,
        event_type=event_type,
        delta=delta,
        actor=actor,
        notes=notes,
    )
    type(container).objects.filter(pk=container.pk).update(
        memory_value_score=F('memory_value_score') + delta
    )


def _maybe_trigger_beryl_summary(discussion):
    """
    Fire Beryl summary candidate generation when post count hits an interval.
    Stub: wired to Switchboard/Beryl in a subsequent pass.
    """
    count = discussion.posts.filter(is_deleted=False).count()
    if count > 0 and count % BERYL_TRIGGER_POST_INTERVAL == 0:
        _generate_beryl_candidate(discussion)


def _generate_beryl_candidate(discussion):
    """
    Request a candidate summary from Beryl and store it in summary_pending.
    Stub — replace with Switchboard call when the integration is ready.
    """
    pass  # noqa: placeholder — Switchboard integration pending


def _maybe_surface_in_worktable(container):
    """
    Surface content in Worktable when memory_value_score exceeds threshold (D16).
    Stub — wired to Worktable queue in a subsequent pass.
    """
    container.refresh_from_db(fields=['memory_value_score'])
    if container.memory_value_score >= MEMORY_VALUE_WORKTABLE_THRESHOLD:
        _enqueue_worktable(container)


def _enqueue_worktable(container):
    """
    Enqueue high-memory-value content for Worktable curator review (D16).
    Stub — replace with concrete Worktable integration.
    """
    pass  # noqa: placeholder — Worktable integration pending


@receiver(post_save, sender=Discussion)
def discussion_created_signal_seed(sender, instance, created, **kwargs):
    """Seed memory-value score from creation_signal when a Discussion is first saved (D9)."""
    if not created or not instance.creation_signal:
        return
    delta = CREATION_SIGNAL_WEIGHTS.get(instance.creation_signal, 0.0)
    if delta:
        _log_event_and_update_score(
            instance,
            MemoryValueEvent.CREATION_SIGNAL_EVENT,
            delta,
            actor=instance.created_by,
        )


@receiver(post_save, sender=FeedPost)
def feed_post_created_signal_seed(sender, instance, created, **kwargs):
    """Seed memory-value score from creation_signal when a FeedPost is first saved (D9)."""
    if not created or not instance.creation_signal:
        return
    delta = CREATION_SIGNAL_WEIGHTS.get(instance.creation_signal, 0.0)
    if delta:
        _log_event_and_update_score(
            instance,
            MemoryValueEvent.CREATION_SIGNAL_EVENT,
            delta,
            actor=instance.author,
        )


@receiver(post_save, sender=Post)
def post_created_memory_update(sender, instance, created, **kwargs):
    """
    Update memory-value score when a new Post is created (D6, D10, D11).
    Fires Beryl trigger for Discussion containers (D12).
    """
    if not created:
        return

    container = instance.container
    if not container or getattr(container, 'is_deleted', False):
        return

    # Base reply weight
    total_delta = REPLY_WEIGHT
    events = [(MemoryValueEvent.REPLY, REPLY_WEIGHT)]

    # Quoted-reply bonus (D10)
    if instance.quoted_post_id:
        events.append((MemoryValueEvent.QUOTED_REPLY, QUOTED_REPLY_BONUS))
        total_delta += QUOTED_REPLY_BONUS

    # Author-distinguished reply bonus (D11)
    if instance.is_author_distinguished:
        events.append((MemoryValueEvent.AUTHOR_REPLY, AUTHOR_REPLY_BONUS))
        total_delta += AUTHOR_REPLY_BONUS

    from django.contrib.contenttypes.models import ContentType
    ct = ContentType.objects.get_for_model(container)
    MemoryValueEvent.objects.bulk_create([
        MemoryValueEvent(
            content_type=ct,
            object_id=container.pk,
            event_type=et,
            delta=d,
            actor=instance.author,
        )
        for et, d in events
    ])
    type(container).objects.filter(pk=container.pk).update(
        memory_value_score=F('memory_value_score') + total_delta
    )

    # Beryl summary trigger (D12) — Discussion only
    if isinstance(container, Discussion):
        _maybe_trigger_beryl_summary(container)

    _maybe_surface_in_worktable(container)


@receiver(post_save, sender=PostReaction)
def reaction_memory_update(sender, instance, created, **kwargs):
    """Update memory-value score when a reaction is added to a Post (D6)."""
    if not created:
        return

    container = instance.post.container
    if not container or getattr(container, 'is_deleted', False):
        return

    _log_event_and_update_score(
        container,
        MemoryValueEvent.REACTION,
        REACTION_WEIGHT,
        actor=instance.user,
    )
    _maybe_surface_in_worktable(container)
