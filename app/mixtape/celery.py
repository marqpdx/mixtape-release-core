# mixtape/celery.py

import os
from celery import Celery
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'cleanup-empty-drafts': {
        'task': 'your_app.tasks.cleanup.cleanup_empty_drafts',
        'schedule': crontab(hour=2, minute=0),  # Run daily at 2 AM
    },
    'cleanup-old-working-copies': {
        'task': 'your_app.tasks.cleanup.cleanup_old_working_copies',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Run weekly on Sunday at 3 AM
    },
}

# Let the environment decide whether to use dev or prod
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "mixtape.settings.dev"))

# Configure Celery broker from environment variable (supports both dev and prod)
# Dev: amqp://guest:guest@localhost//
# Prod: amqp://celery_user:PASSWORD@localhost//
broker_url = os.getenv('CELERY_BROKER_URL', 'amqp://guest:guest@localhost//')

app = Celery('mixtape', broker=broker_url)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Additional RabbitMQ configuration
app.conf.update(
    # Basic settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,

    # Worker settings
    worker_prefetch_multiplier=1,
    task_acks_late=True,

    # Result backend (optional - for storing task results)
    # result_backend='redis://localhost:6379/0',  # or use RabbitMQ: 'rpc://'
    result_backend='rpc://',  # Use RabbitMQ for storing task results
    result_expires=3600,  # 1 hour
)

app.autodiscover_tasks()

# ✅ Defer imports until after Django is ready
@app.on_after_finalize.connect
def import_custom_tasks(sender, **kwargs):
    print("[celery] 🔁 Running import_custom_tasks hook")
    # import ai.tasks
    # import ai.tasks.rabbitmq_tasks
    import utils.tasks.send_transactional_email_task as st
    print("[celery] ✅ All custom tasks imported", st)

# ✅ Force the hook to run immediately after Celery app finalization
app.finalize()
