# mixtape/celery_app.py

# CRITICAL: Import force_cpu FIRST in dev to disable MPS before any torch imports
import os
if os.getenv("DJANGO_ENV") == "dev":
    import force_cpu  # noqa: F401 - Must be first!

from celery import Celery
from kombu import Queue


# If you load .env in dev via python-dotenv (optional but handy):
try:
    from dotenv import load_dotenv  # pip install python-dotenv (dev only)
    load_dotenv()
except Exception:
    pass

# Pick the Django settings module from env; default to dev locally
os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "mixtape.settings.dev"),
)

app = Celery("mixtape")

# ---- Core wiring from environment ----
app.conf.broker_url     = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")
app.conf.result_backend = os.getenv("CELERY_RESULT_BACKEND", "rpc://")

# The default queue handles signal-triggered, time-sensitive tasks
# (activity fanout, push notifications, socket events, email dispatch).
default_q = os.getenv("SHARED_RABBIT_CHAT_QUEUE", "mixtape_shared_rabbit_chat_queue")
app.conf.task_default_queue = default_q

app.conf.task_queues = (
    # ---- Time-sensitive: event-driven tasks ----
    Queue(default_q, routing_key=default_q),

    # ---- Push notifications: isolated so uvicorn/Livewire cannot consume them ----
    # Uvicorn consumes from default_q for real-time events; push tasks must live
    # on a separate queue that only the Celery default-worker knows about.
    Queue("push", routing_key="push"),

    # ---- Low-frequency polling: beat-scheduled maintenance tasks ----
    # Isolated so they don't flood default worker logs or starve push tasks.
    Queue("polling", routing_key="polling"),

    # ---- Compute-heavy: audio transcription (solo pool, torch-safe) ----
    Queue("transcription", routing_key="transcription"),

    # ---- External integrations ----
    Queue("commons", routing_key="commons"),       # URL extraction via Inkwell
    Queue("synopsis_results", routing_key="synopsis_results"),  # FastAPI → Django synopsis
)

# ---- Task routing ----
# RULE: Every task MUST have an explicit route here. Never rely on default_q fallback.
#
# default_q (mixtape_shared_rabbit_chat_queue) is shared with Uvicorn/Livewire.
# Any task that falls through to default_q without an explicit route risks being
# silently consumed by Uvicorn and dropped — no error, no retry, no log.
# This has caused real bugs twice. Do not skip this step when adding a new task.
#
# Queue guide:
#   polling  → beat-scheduled, low-frequency maintenance tasks
#   push     → Celery-only; email, push notifications, anything Uvicorn must not touch
#   transcription → solo pool, torch-safe (audio only)
#   commons  → external integrations (Inkwell URL extraction)
#   default_q → Livewire real-time events only (activity fanout, socket notifications)
app.conf.task_routes = {
    # --- Beat-scheduled polling tasks → isolated polling worker ---
    "stackroom.tasks.processing.process_pending_uploads": {
        "queue": "polling", "routing_key": "polling"
    },
    "groups.tasks.execute_due_ownership_requests": {
        "queue": "polling", "routing_key": "polling"
    },
    "broadcast.tasks.dispatch_scheduled_broadcasts_task": {
        "queue": "polling", "routing_key": "polling"
    },
    "distribution.tasks.recover_missed_publish_events": {
        "queue": "polling", "routing_key": "polling"
    },
    "writing.tasks.publish_scheduled_pieces": {
        "queue": "polling", "routing_key": "polling"
    },

    # --- Transcription → dedicated solo-pool worker (all environments) ---
    "concord.tasks.transcription.transcribe_recording_task": {
        "queue": "transcription", "routing_key": "transcription"
    },
    "concord.tasks.transcription.transcribe_pending_recordings": {
        "queue": "transcription", "routing_key": "transcription"
    },

    # --- External integrations ---
    "inkwell.tasks.synopsis.process_synopsis_result": {
        "queue": "synopsis_results", "routing_key": "synopsis_results"
    },
    "commons.tasks.extract_commons_item_task": {
        "queue": "commons", "routing_key": "commons"
    },

    # --- Default queue (explicit routes remove ambiguity in all calling contexts) ---
    "activity.tasks.fanout_action_task": {
        "queue": default_q, "routing_key": default_q
    },
    "activity.tasks.dispatch_push_notification_task": {
        "queue": "push", "routing_key": "push"
    },
    "activity.tasks.dispatch_socket_notification_task": {
        "queue": default_q, "routing_key": default_q
    },
    "broadcast.tasks.dispatch_broadcast_email_task": {
        "queue": default_q, "routing_key": default_q
    },
    "utils.tasks.send_transactional_email_task": {
        "queue": "push", "routing_key": "push"
    },
    "groups.tasks.send_invitation_email": {
        "queue": "push", "routing_key": "push"
    },
    "activity.tasks.poll_push_receipts_task": {
        "queue": "push", "routing_key": "push"
    },
}

# ---- Sensible defaults ----
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=os.getenv("TIME_ZONE", "UTC"),
    enable_utc=True,
    worker_prefetch_multiplier=1,  # Hold exactly one task per worker (task_acks_late=True)
    task_acks_late=True,
    result_expires=3600,   # 1 hour
    worker_hijack_root_logger=False,  # Preserve Django LOGGING config in worker processes
)

# ---- Beat schedule ----
# Beat only schedules; tasks execute on the worker consuming the routed queue.
# Polling tasks → "polling" worker. See task_routes above.
app.conf.beat_schedule = {
    "process-pending-uploads": {
        "task": "stackroom.tasks.processing.process_pending_uploads",
        "schedule": 60.0,  # Ingestion lag of up to 60s is acceptable; was 15s (too aggressive)
    },
    "execute-due-ownership-requests": {
        "task": "groups.tasks.execute_due_ownership_requests",
        "schedule": 60.0,
    },
    "dispatch-scheduled-broadcasts": {
        "task": "broadcast.tasks.dispatch_scheduled_broadcasts_task",
        "schedule": 60.0,
    },
    "recover-missed-publish-events": {
        "task": "distribution.tasks.recover_missed_publish_events",
        "schedule": 300.0,  # every 5 minutes
    },
    "publish-scheduled-pieces": {
        "task": "writing.tasks.publish_scheduled_pieces",
        "schedule": 60.0,
    },
}

# Discover tasks.py in all INSTALLED_APPS
app.autodiscover_tasks()

# Import worker init hooks to register worker_process_init signal
import mixtape.worker_init  # noqa: F401 - Registers signal handlers

# (Optional) your import hook — leave it, but make it safe
@app.on_after_finalize.connect
def import_custom_tasks(sender, **kwargs):
    print("[celery] 🔁 Running import_custom_tasks hook")
    try:
        import utils.tasks.send_transactional_email_task as st  # noqa: F401
        print("[celery] ✅ All custom tasks imported")
    except Exception as e:
        print(f"[celery] ⚠ custom task import skipped: {e}")
