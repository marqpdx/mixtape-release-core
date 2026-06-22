# threadworks/tasks.py
#
# Scheduled maintenance tasks for Threadworks (Phase 2).

from celery import shared_task
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from threadworks.models import Discussion, FeedPost, MemoryValueEvent
from threadworks.memory_signals import (
    BASE_DECAY_RATE,
    DECAY_MODE,
    TIMELINESS_DECAY_RATE,
)


def _apply_decay(model, rate, mode, queryset, notes_suffix=""):
    """
    Apply one decay step to a queryset of Discussion or FeedPost.

    Fetches current scores, creates MemoryValueEvent records (negative delta),
    then updates scores atomically via SQL. Wrapped in atomic() so the event
    log and score stay in sync.
    """
    ct = ContentType.objects.get_for_model(model)
    items = list(queryset.values("pk", "memory_value_score"))
    if not items:
        return 0

    events = []
    for item in items:
        old_score = item["memory_value_score"]
        if mode == "exponential":
            new_score = max(0.0, old_score * (1.0 - rate))
        else:  # linear
            new_score = max(0.0, old_score - rate)
        delta = new_score - old_score
        if delta == 0.0:
            continue
        events.append(
            MemoryValueEvent(
                content_type=ct,
                object_id=item["pk"],
                event_type=MemoryValueEvent.DECAY,
                delta=delta,
                notes=f"mode={mode} rate={rate}{notes_suffix}",
            )
        )

    if not events:
        return 0

    affected_pks = [e.object_id for e in events]
    with transaction.atomic():
        MemoryValueEvent.objects.bulk_create(events)
        qs_affected = queryset.filter(pk__in=affected_pks)
        if mode == "exponential":
            qs_affected.update(
                memory_value_score=Greatest(0.0, F("memory_value_score") * (1.0 - rate))
            )
        else:
            qs_affected.update(
                memory_value_score=Greatest(0.0, F("memory_value_score") - rate)
            )

    return len(events)


@shared_task(bind=True, max_retries=2)
def apply_memory_value_decay_task(self):
    """
    Daily decay job for Discussion and FeedPost memory_value_score (Phase 2, ADR-0047 §7).

    Content with a past timeliness_date decays at TIMELINESS_DECAY_RATE;
    all other content uses BASE_DECAY_RATE. Decay is logged as MemoryValueEvent
    records (negative delta) for auditing and retroactive reweighting.
    """
    today = timezone.now().date()
    total = 0

    for model in (Discussion, FeedPost):
        live = model.objects.filter(is_deleted=False, memory_value_score__gt=0)

        # Past timeliness_date: accelerated decay
        timeliness_past = live.filter(timeliness_date__lt=today)
        total += _apply_decay(
            model, TIMELINESS_DECAY_RATE, DECAY_MODE, timeliness_past,
            notes_suffix=" timeliness_expired"
        )

        # Everything else: base decay (includes null timeliness_date)
        normal = live.exclude(timeliness_date__lt=today)
        total += _apply_decay(model, BASE_DECAY_RATE, DECAY_MODE, normal)

    return {"decayed": total, "date": str(today)}
