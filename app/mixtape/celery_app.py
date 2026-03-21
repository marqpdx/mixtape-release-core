# mixtape/celery.py

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

default_q = os.getenv("SHARED_RABBIT_CHAT_QUEUE", "mixtape_shared_rabbit_chat_queue")
app.conf.task_default_queue = default_q
task_queues = [
    Queue(default_q, routing_key=default_q),
    Queue("synopsis_results", routing_key="synopsis_results"),  # For FastAPI → Django synopsis communication
    Queue("commons", routing_key="commons"),  # Commons URL extraction via Inkwell
]

# Dev-only: isolate transcription tasks to avoid prefork + torch issues
if os.getenv("DJANGO_ENV") == "dev":
    task_queues.append(Queue("transcription", routing_key="transcription"))

app.conf.task_queues = tuple(task_queues)

# Optional explicit routing (keep or remove if not needed)
task_routes = {
    "utils.tasks.send_transactional_email_task": {
        "queue": default_q, "routing_key": default_q
    },
    "inkwell.tasks.synopsis.process_synopsis_result": {
        "queue": "synopsis_results", "routing_key": "synopsis_results"
    },
    "commons.tasks.extract_commons_item_task": {
        "queue": "commons", "routing_key": "commons"
    },
}

if os.getenv("DJANGO_ENV") == "dev":
    task_routes.update({
        "concord.tasks.transcription.transcribe_recording_task": {
            "queue": "transcription", "routing_key": "transcription"
        },
        "concord.tasks.transcription.transcribe_pending_recordings": {
            "queue": "transcription", "routing_key": "transcription"
        },
    })

app.conf.task_routes = task_routes

# ---- Sensible defaults (no need to keep in Django settings) ----
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=os.getenv("TIME_ZONE", "UTC"),
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    result_expires=3600,   # 1 hour
)

# ---- Beat schedule (code-defined; move to django-celery-beat later if desired) ----
app.conf.beat_schedule = {
    "process-pending-uploads": {
        "task": "stackroom.tasks.processing.process_pending_uploads",
        "schedule": 15.0,  # Run every 15 seconds
    },
    "execute-due-ownership-requests": {
        "task": "groups.tasks.execute_due_ownership_requests",
        "schedule": 60.0,  # Every 1 minute
    },
    "dispatch-scheduled-broadcasts": {
        "task": "broadcast.tasks.dispatch_scheduled_broadcasts_task",
        "schedule": 60.0,  # Every 1 minute
    },
    # "cleanup-empty-drafts": {
    #     "task": "your_app.tasks.cleanup.cleanup_empty_drafts",
    #     "schedule": crontab(hour=2, minute=0),
    # },
    # "cleanup-old-working-copies": {
    #     "task": "your_app.tasks.cleanup.cleanup_old_working_copies",
    #     "schedule": crontab(hour=3, minute=0, day_of_week=0),
    # },
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
