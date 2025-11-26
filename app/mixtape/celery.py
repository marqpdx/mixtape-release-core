# mixtape/celery.py
import os
from celery import Celery
from kombu import Queue
from celery.schedules import crontab

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

default_q = os.getenv("CELERY_TASK_DEFAULT_QUEUE", "stage_queue")
app.conf.task_default_queue = default_q
app.conf.task_queues = (
    Queue(default_q, routing_key=default_q),
)

# Optional explicit routing (keep or remove if not needed)
app.conf.task_routes = {
    "utils.tasks.send_transactional_email_task": {
        "queue": default_q, "routing_key": default_q
    },
}

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
# app.conf.beat_schedule = {
#     "cleanup-empty-drafts": {
#         "task": "your_app.tasks.cleanup.cleanup_empty_drafts",
#         "schedule": crontab(hour=2, minute=0),
#     },
#     "cleanup-old-working-copies": {
#         "task": "your_app.tasks.cleanup.cleanup_old_working_copies",
#         "schedule": crontab(hour=3, minute=0, day_of_week=0),
#     },
# }

# Discover tasks.py in all INSTALLED_APPS
app.autodiscover_tasks()

# (Optional) your import hook — leave it, but make it safe
@app.on_after_finalize.connect
def import_custom_tasks(sender, **kwargs):
    print("[celery] 🔁 Running import_custom_tasks hook")
    try:
        import utils.tasks.send_transactional_email_task as st  # noqa: F401
        print("[celery] 📦 utils.tasks loaded and task imported")
        print("[celery] ✅ All custom tasks imported")
    except Exception as e:
        print(f"[celery] ⚠ custom task import skipped: {e}")
