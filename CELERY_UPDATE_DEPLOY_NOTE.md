# Celery Update Deploy Note

Repo: `mixtape-release-core`
Date: 2026-08-24
Scope: Celery local launchers, task routing, and server worker coverage

## Purpose

This update fixes queue leakage and routing drift in the Celery worker setup.
Before this change, several local "dedicated" workers also consumed `push`, task
routing had stale/mismatched task names, and the `switchboard` and
`synopsis_results` queues had routes but no checked-in worker launchers or
systemd units.

## Source Changes To Deploy

Ensure the server checkout includes these repository changes:

- `app/mixtape/celery_app.py`
  - Added explicit routes for previously missing live tasks.
  - Removed stale writing cleanup routes.
  - Added `atrium.tasks.keeper_compact_task` route to `catalyst`.
  - Removed the redundant `import_custom_tasks` finalize hook.
- `app/assets/tasks/cleanup.py`
  - `delete_image_async` now registers as `assets.tasks.delete_image_async`.
- `app/assets/tasks/upload.py`
  - `upload_group_asset_task` now registers as `assets.tasks.upload_group_asset_task`.
- `app/atrium/tasks.py`
  - `keeper_compact_task` no longer uses phantom `queue="default"`.
- `app/writing/tasks/cleanup.py`
  - Removed. These tasks were not autodiscovered and one referenced a non-existent model.
- Local launchers:
  - `run_celery_local.sh`
  - `run_celery_polling_local.sh`
  - `run_celery_commons_local.sh`
  - `run_celery_push_local.sh`
  - `run_celery_transcription_local.sh`
  - `run_celery_catalyst_local.sh`
  - `run_celery_ocr_local.sh`
  - `run_celery_switchboard_local.sh`
  - `run_celery_synopsis_results_local.sh`
  - `run_celery_check.sh`
- New systemd unit templates:
  - `crossroads-celery-catalyst.service`
  - `crossroads-celery-ocr.service`
  - `crossroads-celery-switchboard.service`
  - `crossroads-celery-synopsis-results.service`

## Server Actions

1. Stop Celery services before changing files.

   Stop all deployed Celery workers and Celery beat. Confirm no old beat process
   remains alive before restarting.

2. Remove stale beat schedule state.

   From the deployed Django app working directory, remove any local beat schedule
   database files, typically:

   ```bash
   rm -f /var/www/crossroads/app/app/celerybeat-schedule.db
   rm -f /var/www/crossroads/app/app/celerybeat-schedule.db.*
   ```

3. Install or update systemd unit files.

   Existing worker services should consume exactly one queue where dedicated:

   - polling worker: `-Q polling`
   - commons worker: `-Q commons`
   - push worker: `-Q push`
   - transcription worker: `-Q transcription`
   - catalyst worker: `-Q catalyst`
   - ocr worker: `-Q ocr`
   - switchboard worker: `-Q switchboard`
   - synopsis results worker: `-Q synopsis_results`

   Add units equivalent to:

   - `crossroads-celery-catalyst.service`
   - `crossroads-celery-ocr.service`
   - `crossroads-celery-switchboard.service`
   - `crossroads-celery-synopsis-results.service`

   After copying units into systemd, run:

   ```bash
   systemctl daemon-reload
   systemctl enable crossroads-celery-catalyst.service
   systemctl enable crossroads-celery-ocr.service
   systemctl enable crossroads-celery-switchboard.service
   systemctl enable crossroads-celery-synopsis-results.service
   ```

4. Restart with exactly one beat process.

   Start Celery beat once, then start the workers. Do not start a second beat
   process against the same broker.

5. Verify queue isolation.

   Confirm each worker logs only its intended queue. In particular:

   - polling must not consume `push`
   - commons must not consume `push`
   - transcription must not consume `push`
   - switchboard has an active consumer
   - synopsis_results has an active consumer

6. Verify schedule cadence.

   Watch polling logs for at least 70 seconds. These tasks should enqueue about
   once per minute, not once per second:

   - `ops.tasks.collect_postgres_snapshot`
   - `ops.tasks.collect_application_snapshot`
   - `writing.tasks.publish_scheduled_pieces`
   - `broadcast.tasks.dispatch_scheduled_broadcasts_task`
   - `groups.tasks.execute_due_ownership_requests`

## Local Verification Already Run

The local checkout passed:

```bash
bash -n run_celery_*.sh
git diff --check
./run_celery_check.sh
```

Static route audit result:

```text
TOTAL_TASKS 61 ROUTES 73 MISSING 0
```

## Deployment Risk Notes

- The old `app/celerybeat-schedule.db` can recreate the observed log storm if
  reused with stale runtime state.
- More than one beat process against the same broker can duplicate scheduled
  task dispatch.
- `SHARED_RABBIT_CHAT_QUEUE` should remain the app default / Livewire queue. Do
  not use it to select dedicated worker queues.
