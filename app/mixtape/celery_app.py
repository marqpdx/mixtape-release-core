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

    # ---- Catalyst: long-running Claude subprocess jobs (isolated from push) ----
    # run_file_semantic_analysis blocks a worker for 3-4 min per file (claude -p subprocess).
    # A dedicated queue prevents parse jobs from starving push notifications or email tasks.
    Queue("catalyst", routing_key="catalyst"),

    # ---- OCR spike: document page rendering + local OCR engine calls ----
    Queue("ocr", routing_key="ocr"),

    # ---- External integrations ----
    Queue("commons", routing_key="commons"),       # URL extraction via Inkwell
    Queue("synopsis_results", routing_key="synopsis_results"),  # FastAPI → Django synopsis

    # ---- Switchboard: AI worker (summarize, classify, think) ----
    Queue("switchboard", routing_key="switchboard"),
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
#   ocr      → OCR spike document rendering and local OCR engine calls
#   commons  → external integrations (Inkwell URL extraction)
#   default_q → Livewire real-time events only (activity fanout, socket notifications)
app.conf.task_routes = {
    # --- Beat-scheduled polling tasks → isolated polling worker ---
    "recurring_action.tasks.advance_recurring_actions": {
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

    # --- External integrations / AI / Inkwell ---
    "inkwell.tasks.synopsis.process_synopsis_result": {
        "queue": "synopsis_results", "routing_key": "synopsis_results"
    },
    "inkwell.tasks.synopsis.generate_synopsis_task": {
        "queue": "commons", "routing_key": "commons"
    },
    "inkwell.tasks.rabbitmq_tasks.send_task_to_fastapi": {
        "queue": "commons", "routing_key": "commons"
    },
    "inkwell.tasks.rabbitmq_tasks.start_rabbitmq_polling": {
        "queue": "commons", "routing_key": "commons"
    },
    "inkwell.tasks.rabbitmq_tasks.poll_rabbitmq_results": {
        "queue": "commons", "routing_key": "commons"
    },
    "inkwell.tasks.rabbitmq_tasks.process_task_result": {
        "queue": "commons", "routing_key": "commons"
    },
    "inkwell.tasks.rabbitmq_tasks.manual_stop_polling": {
        "queue": "commons", "routing_key": "commons"
    },
    "ai.tasks.ingest.ingest_approved_asset_task": {
        "queue": "commons", "routing_key": "commons"
    },
    "commons.tasks.extract_commons_item_task": {
        "queue": "commons", "routing_key": "commons"
    },

    # --- Stackroom integration: ingest + deactivation ---
    "inkwell.tasks.stackroom_integration.ingest_object_task": {
        "queue": "commons", "routing_key": "commons"
    },
    "inkwell.tasks.stackroom_integration.deactivate_object_task": {
        "queue": "commons", "routing_key": "commons"
    },

    # --- Prospects: file parsing + voice transcription ---
    "prospects.tasks.parse_prospect_file_task": {
        "queue": "commons", "routing_key": "commons"
    },
    "prospects.tasks.transcribe_prospect_voice_task": {
        "queue": "transcription", "routing_key": "transcription"
    },

    # --- Profiles: intro voice transcription ---
    "profiles.tasks.transcribe_intro_voice_task": {
        "queue": "transcription", "routing_key": "transcription"
    },

    # --- Feedback: voice transcription ---
    "feedback.tasks.transcribe_feedback_voice_task": {
        "queue": "transcription", "routing_key": "transcription"
    },

    # --- MediaCapture: screencast transcription + Stackroom ingestion ---
    "media_capture.tasks.transcribe_capture": {
        "queue": "transcription", "routing_key": "transcription"
    },
    "media_capture.tasks.ingest_to_stackroom": {
        "queue": "commons", "routing_key": "commons"
    },

    # --- Initiatives: AI-backed quality scan, rolling summary, handover draft ---
    "initiatives.tasks.run_artifact_quality_scan": {
        "queue": "commons", "routing_key": "commons"
    },
    "initiatives.tasks.update_rolling_summary": {
        "queue": "commons", "routing_key": "commons"
    },
    "initiatives.tasks.handover_task": {
        "queue": "commons", "routing_key": "commons"
    },

    # --- Assets: upload and cleanup ---
    "assets.tasks.upload_group_asset_task": {
        "queue": "push", "routing_key": "push"
    },
    "assets.tasks.delete_image_async": {
        "queue": "push", "routing_key": "push"
    },

    # --- Distribution: event-triggered publish ---
    "distribution.tasks.execute_scheduled_publish_event": {
        "queue": "push", "routing_key": "push"
    },

    # --- Writing: cleanup, transcription, and AI split suggestion ---
    "writing.tasks.generate_split_suggestion_task": {
        "queue": "commons", "routing_key": "commons"
    },
    "writing.tasks.enqueue_writing_piece_synopsis_task": {
        "queue": "commons", "routing_key": "commons"
    },
    "writing.tasks.transcribe_seed_task": {
        "queue": "transcription", "routing_key": "transcription"
    },
    "console.tasks.transcribe_hub_capture_task": {
        "queue": "transcription", "routing_key": "transcription"
    },
    "initiatives.tasks.transcribe_initiatives_job": {
        "queue": "transcription", "routing_key": "transcription"
    },
    "threadworks.tasks.apply_memory_value_decay_task": {
        "queue": "polling", "routing_key": "polling"
    },
    "ops.tasks.collect_postgres_snapshot": {
        "queue": "polling", "routing_key": "polling"
    },
    "ops.tasks.collect_application_snapshot": {
        "queue": "polling", "routing_key": "polling"
    },

    # --- Switchboard: AI worker tasks (classify, summarize, context_shape, think, retrieve, draft) ---
    "switchboard.classify_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.summarize_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.context_shape_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.think_cluster_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.retrieve_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.draft_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.refine_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.research_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.pattern_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.synthesize_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.synthesize_narrative_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },
    "switchboard.synopsis_linkedin_async": {
        "queue": "switchboard", "routing_key": "switchboard"
    },

    # --- Puddlejump: snapshot generation + beat scan + Stackroom ingest + retrieve/find ---
    "puddlejump.tasks.generate_snapshot": {
        "queue": "push", "routing_key": "push"
    },
    "puddlejump.tasks.run_scheduled_snapshots": {
        "queue": "polling", "routing_key": "polling"
    },
    "puddlejump.tasks.ingest_library_item": {
        "queue": "commons", "routing_key": "commons"
    },

    # --- Concord: audio interpretation ---
    "concord.tasks.interpretation.interpret_recording_task": {
        "queue": "transcription", "routing_key": "transcription"
    },

    # --- Chat: voice message transcription ---
    "chat.tasks.transcribe_chat_message_task": {
        "queue": "transcription", "routing_key": "transcription"
    },
    "chat.tasks.emit_transcript_ready_task": {
        "queue": default_q, "routing_key": default_q
    },
    "chat.tasks.enforce_retention_policies": {
        "queue": "polling", "routing_key": "polling"
    },
    "utils.chat.notify_socket_server": {
        "queue": default_q, "routing_key": default_q
    },

    # --- Livewire real-time events (default_q intentional — Uvicorn also consumes) ---
    "activity.tasks.fanout_action_task": {
        "queue": default_q, "routing_key": default_q
    },
    "activity.tasks.dispatch_socket_notification_task": {
        "queue": default_q, "routing_key": default_q
    },

    # --- Email and push notifications (push queue = Celery-only) ---
    "activity.tasks.dispatch_push_notification_task": {
        "queue": "push", "routing_key": "push"
    },
    "activity.tasks.poll_push_receipts_task": {
        "queue": "push", "routing_key": "push"
    },
    "broadcast.tasks.dispatch_broadcast_email_task": {
        "queue": "push", "routing_key": "push"
    },
    "utils.tasks.send_transactional_email_task": {
        "queue": "push", "routing_key": "push"
    },
    "groups.tasks.send_invitation_email": {
        "queue": "push", "routing_key": "push"
    },

    # --- Catalyst: activation + provisioning (short, stay on push) ---
    "catalyst.tasks.send_catalyst_activation_email": {
        "queue": "push", "routing_key": "push"
    },
    "catalyst.tasks.provision_catalyst_for_group": {
        "queue": "push", "routing_key": "push"
    },
    # --- Catalyst: async parse pipeline (dedicated queue — claude -p subprocesses block 3-4 min/file) ---
    "catalyst.tasks.run_file_semantic_analysis": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "catalyst.tasks.finalize_parse_job": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "catalyst.tasks.materialize_register_entities": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "writing.tasks.generate_linkedin_copy_with_claude_code": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "atrium.tasks.keeper_compact_task": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "atrium.tasks.keepers.register_recency_keeper_task": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "atrium.tasks.keepers.answer_recency_question": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "scrap.tasks.answer_raw_scrap_pile_question": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "console.tasks.register_inbox_keeper_task": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    "console.tasks.answer_inbox_type_guess": {
        "queue": "catalyst", "routing_key": "catalyst"
    },
    # --- OCR Spike: isolated evaluation workflow ---
    "ocr_spike.tasks.run_local_ocr_for_artifact": {
        "queue": "ocr", "routing_key": "ocr"
    },
    "ocr_spike.tasks.run_cloud_ocr_for_page": {
        "queue": "ocr", "routing_key": "ocr"
    },
    "ocr_spike.tasks.run_recipe_shape_for_page": {
        "queue": "ocr", "routing_key": "ocr"
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
    # process-pending-uploads removed at CP4 — now runs inside standalone stackroom service
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
    "collect-postgres-snapshot": {
        "task": "ops.tasks.collect_postgres_snapshot",
        "schedule": 60.0,
    },
    "collect-application-snapshot": {
        "task": "ops.tasks.collect_application_snapshot",
        "schedule": 60.0,
    },
    "run-scheduled-snapshots": {
        "task": "puddlejump.tasks.run_scheduled_snapshots",
        "schedule": 3600.0,  # hourly — covers all frequencies (hourly checks are still gated by last_snapshot_at)
    },
    "advance-recurring-actions": {
        "task": "recurring_action.tasks.advance_recurring_actions",
        "schedule": 900.0,  # every 15 minutes
    },
    "apply-memory-value-decay": {
        "task": "threadworks.tasks.apply_memory_value_decay_task",
        "schedule": 86400.0,  # daily — tune cadence alongside weight parameters
    },
    "ensure-recency-keeper-registered": {
        "task": "atrium.tasks.keepers.register_recency_keeper_task",
        "schedule": 300.0,  # every 5 minutes — RecencyKeeper is long-lived infra, not spawned per-request (K-5)
    },
    "ensure-inbox-keeper-registered": {
        "task": "console.tasks.register_inbox_keeper_task",
        "schedule": 300.0,  # every 5 minutes — same rationale as RecencyKeeper's heartbeat (K-7)
    },
}

# Discover tasks.py in all INSTALLED_APPS
app.autodiscover_tasks()

# Import worker init hooks to register worker_process_init signal
import mixtape.worker_init  # noqa: F401 - Registers signal handlers
