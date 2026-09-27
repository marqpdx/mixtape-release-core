# writing/tasks.py

import json
import logging
import hashlib
import os
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from celery import shared_task

from concord.services.whisper import transcribe_audio
from writing.models import Seed

logger = logging.getLogger(__name__)


@shared_task(queue="polling")
def publish_scheduled_pieces():
    """
    Beat task: flip WritingPieces from status='scheduled' to 'published'
    when their scheduled_for time has arrived.
    Runs every 60s.
    """
    from django.utils.timezone import now
    from writing.models import WritingPiece

    due = WritingPiece.objects.filter(
        status="scheduled",
        scheduled_for__lte=now(),
    ).select_related("author")

    count = 0
    for piece in due:
        try:
            piece.publish()
            count += 1
            logger.info("[scheduler] Published piece %s (%s)", piece.id, piece.slug)
        except Exception as exc:
            logger.error("[scheduler] Failed to publish piece %s: %s", piece.id, exc, exc_info=True)

    return {"published": count}


def _notify_seed_transcribed(seed: Seed) -> None:
    """Push seed:transcribed to the owner's socket via Livewire /notify. Fire-and-forget."""
    livewire_url = getattr(settings, "LIVEWIRE_INTERNAL_URL", "http://127.0.0.1:5001")
    secret = getattr(settings, "LIVEWIRE_NOTIFY_SECRET", "")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Notify-Secret"] = secret
    try:
        requests.post(
            f"{livewire_url}/notify",
            json={
                "event": "seed:transcribed",
                "username": seed.author.username,
                "payload": {"seed_id": str(seed.id), "body_text": seed.body_text or ""},
            },
            headers=headers,
            timeout=3,
        )
    except Exception as exc:
        logger.warning("[seeds] Failed to notify livewire of transcription: %s", exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10, queue="transcription")
def transcribe_seed_task(self, seed_id: str):
    """
    Background transcription for voice seeds.
    """
    try:
        seed = Seed.objects.select_related("author").get(id=seed_id)
    except Seed.DoesNotExist:
        logger.error("[seeds] Seed %s not found", seed_id)
        return {"status": "missing"}

    if seed.kind != "voice":
        return {"status": "skipped", "reason": "not_voice"}

    if not seed.audio_file or not seed.audio_file.file_path:
        seed.status = "failed"
        seed.transcript_error = "Missing audio file."
        seed.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": "missing_audio"}

    try:
        seed.status = "processing"
        seed.save(update_fields=["status", "updated_at"])
        result = transcribe_audio(seed.audio_file.file_path)
        transcript = (result.text or "").strip()
        transcript_hash = hashlib.sha256(transcript.encode("utf-8")).hexdigest() if transcript else ""

        seed.transcript_text = transcript
        seed.body_text = transcript
        seed.transcript_hash = transcript_hash
        seed.body_hash = transcript_hash
        seed.edited_after_transcription = False
        seed.status = "ready"
        seed.transcript_provider = result.backend or "whisper"
        seed.transcript_model = result.model_name
        seed.transcript_backend = result.backend
        seed.transcript_created_at = timezone.now()
        seed.transcript_error = ""
        seed.save(update_fields=[
            "transcript_text",
            "body_text",
            "transcript_hash",
            "body_hash",
            "edited_after_transcription",
            "status",
            "transcript_provider",
            "transcript_model",
            "transcript_backend",
            "transcript_created_at",
            "transcript_error",
            "updated_at",
        ])
        _notify_seed_transcribed(seed)
        return {"status": "ok", "chars": len(transcript)}
    except Exception as exc:
        logger.error("[seeds] Transcription failed for %s: %s", seed_id, exc, exc_info=True)
        seed.status = "failed"
        seed.transcript_error = str(exc)
        seed.save(update_fields=["status", "transcript_error", "updated_at"])
        raise self.retry(exc=exc)


@shared_task(
    name="writing.tasks.generate_split_suggestion_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def generate_split_suggestion_task(self, suggestion_id: str):
    """
    Ask Claude to find natural split points in a WritingPiece.
    Receives a SplitSuggestion ID already created as 'pending'.
    Extracts plain text from WorkingDocument.body_json, sends to Claude,
    parses JSON response, updates suggestion to 'ready'.
    """
    from writing.models import SplitSuggestion, WorkingDocument
    from utils.writing.writing_utils import extract_text_from_prosemirror

    try:
        suggestion = SplitSuggestion.objects.select_related("piece__author").get(id=suggestion_id)
    except SplitSuggestion.DoesNotExist:
        logger.error("[split] SplitSuggestion %s not found", suggestion_id)
        return

    if suggestion.status != "pending":
        logger.info("[split] Suggestion %s is no longer pending (%s), skipping", suggestion_id, suggestion.status)
        return

    piece = suggestion.piece

    wc = WorkingDocument.objects.filter(piece=piece, user=piece.author).first()
    if not wc or not wc.body_json:
        logger.error("[split] No working document for piece %s", piece.id)
        suggestion.status = "dismissed"
        suggestion.save(update_fields=["status", "updated_at"])
        return

    plain_text = extract_text_from_prosemirror(wc.body_json)
    if not plain_text or len(plain_text.split()) < 50:
        logger.info("[split] Piece %s too short for split analysis", piece.id)
        suggestion.status = "dismissed"
        suggestion.save(update_fields=["status", "updated_at"])
        return

    paragraphs = [p.strip() for p in plain_text.split("\n") if p.strip()]
    if len(paragraphs) < 3:
        logger.info("[split] Piece %s has too few paragraphs to split", piece.id)
        suggestion.status = "dismissed"
        suggestion.save(update_fields=["status", "updated_at"])
        return

    numbered = "\n".join(f"{i}: {p}" for i, p in enumerate(paragraphs))
    prompt = (
        f"You are a writing editor. Analyze the following article ({len(paragraphs)} paragraphs, "
        f"numbered 0 to {len(paragraphs) - 1}) and identify 1-2 natural split points where it "
        f"could be divided into separate, complete pieces.\n\n"
        f"Look for: transitions in subject matter, perspective shifts, or natural chapter-like breaks. "
        f"Each resulting piece should stand on its own.\n\n"
        f"ARTICLE:\n{numbered}\n\n"
        f"Respond with ONLY a JSON array (no markdown, no explanation):\n"
        f'[{{"after_paragraph_index": <int>, "rationale": "<one sentence>"}}]\n\n'
        f"Return 1 or 2 split points, or [] if the article does not have clear split points."
    )

    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        parsed = json.loads(raw)

        validated = []
        for item in parsed:
            if isinstance(item, dict) and "after_paragraph_index" in item and "rationale" in item:
                idx = int(item["after_paragraph_index"])
                if 0 <= idx < len(paragraphs) - 1:
                    validated.append({
                        "after_paragraph_index": idx,
                        "rationale": str(item["rationale"])[:500],
                    })

        suggestion.suggestions = validated
        suggestion.status = "ready"
        suggestion.generated_at = timezone.now()
        suggestion.save(update_fields=["suggestions", "status", "generated_at", "updated_at"])
        logger.info("[split] Generated %d split point(s) for piece %s", len(validated), piece.id)

    except json.JSONDecodeError as exc:
        logger.error("[split] AI returned invalid JSON for piece %s: %s", piece.id, exc)
        suggestion.status = "dismissed"
        suggestion.save(update_fields=["status", "updated_at"])

    except Exception as exc:
        logger.error("[split] Task failed for piece %s: %s", piece.id, exc, exc_info=True)
        suggestion.status = "dismissed"
        suggestion.save(update_fields=["status", "updated_at"])
        raise self.retry(exc=exc)


@shared_task(name="writing.tasks.enqueue_writing_piece_synopsis_task")
def enqueue_writing_piece_synopsis_task(piece_id: str):
    """
    Create an ActionRun and enqueue switchboard.summarize_async for a published WritingPiece.
    Fires after SynopsisGenerationService runs (rule-based pass). The Switchboard result
    writes back to WritingSynopsis.teaser / description via the on_action_run_saved signal.
    """
    from django.conf import settings
    from writing.models import WritingPiece
    from writing.synopsis_service import _extract_plain_text
    from initiatives.models import ActionRun, ActionRunStatus, ActionRunExecutionMode, ActionRunInitiatorType
    from mixtape.celery_app import app as celery_app

    _DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
    _DEFAULT_TENANT_NAMESPACE = "platform:crossroads"

    try:
        piece = WritingPiece.objects.get(id=piece_id)
    except WritingPiece.DoesNotExist:
        logger.warning("[synopsis_ai] WritingPiece %s not found — skipping", piece_id)
        return

    text = _extract_plain_text(piece.body_json or {}, char_limit=600)
    if not text or len(text.split()) < 30:
        logger.info("[synopsis_ai] Piece %s too short for AI synopsis — skipping", piece_id)
        return

    tenant_id = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", _DEFAULT_TENANT_ID))
    tenant_namespace = str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", _DEFAULT_TENANT_NAMESPACE))

    summarize_payload = {
        "text": text,
        "content_type": "writing.piece",
        "words": 120,
        "style": "neutral",
        "summary_style": "standard",
        "source_id": str(piece_id),
    }

    action_run = ActionRun.objects.create(
        tool_name="writing.summarize",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.SYSTEM,
        initiator_id=str(piece_id),
        request_payload={"piece_id": str(piece_id), "content_type": "writing.piece"},
    )

    celery_app.send_task(
        "switchboard.summarize_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": None,
            "principal_service_token_id": None,
            "request_payload": summarize_payload,
            "summarize_payload": summarize_payload,
        },
        queue="switchboard",
    )

    logger.info("[synopsis_ai] Enqueued summarize action_run=%s for piece=%s", action_run.id, piece_id)


@shared_task(
    name="writing.tasks.generate_linkedin_copy_with_claude_code",
    soft_time_limit=360,
    time_limit=390,
)
def generate_linkedin_copy_with_claude_code(
    *,
    action_run_id: str,
    tenant_id: str,
    tenant_namespace: str,
    principal_user_id: str | None,
    principal_service_token_id: str | None,
    request_payload: dict,
    synopsis_payload: dict,
):
    """Complete a governed LinkedIn ActionRun through tenant-scoped Claude Code."""
    from django.contrib.contenttypes.models import ContentType

    from groups.models.group import Group
    from initiatives.models import ActionRun, ActionRunStatus
    from tenant_runtime.models import TenantClaudeRuntime
    from writing.linkedin_copy_service import generate_linkedin_copy

    try:
        action_run = ActionRun.objects.get(pk=action_run_id)
    except ActionRun.DoesNotExist:
        logger.error("[linkedin-copy] ActionRun %s not found", action_run_id)
        return {"status": "missing", "action_run_id": action_run_id}

    if action_run.status in {ActionRunStatus.SUCCEEDED, ActionRunStatus.FAILED}:
        logger.info(
            "[linkedin-copy] ActionRun %s already terminal (%s); skipping",
            action_run_id,
            action_run.status,
        )
        return {"status": "skipped", "action_run_id": action_run_id}

    try:
        if action_run.tool_name != "writing.synopsis_linkedin":
            raise ValueError("ActionRun tool does not match LinkedIn generation.")
        if str(action_run.tenant_id) != str(tenant_id):
            raise ValueError("ActionRun tenant does not match dispatched tenant.")
        if not action_run.cloud_approved:
            raise ValueError("LinkedIn cloud generation was not approved.")
        if principal_user_id and action_run.initiator_id != str(principal_user_id):
            raise ValueError("ActionRun initiator does not match dispatched principal.")

        run_as_user = None
        cwd = str(settings.BASE_DIR)
        runtime = None
        group = Group.objects.filter(pk=tenant_id, is_active=True).first()
        if group:
            group_ct = ContentType.objects.get_for_model(group)
            runtime = TenantClaudeRuntime.objects.filter(
                tenant_content_type=group_ct,
                tenant_object_id=group.id,
            ).first()

        if runtime:
            if runtime.status != TenantClaudeRuntime.STATUS_READY:
                raise RuntimeError(f"Tenant Claude runtime is not ready ({runtime.status}).")
            allowed_modes = set(runtime.allowed_ai_modes or [])
            accepted_modes = {"linkedin_copy", "synopsis_linkedin", "writing.synopsis_linkedin"}
            if allowed_modes and not allowed_modes.intersection(accepted_modes):
                raise RuntimeError("Tenant Claude runtime does not permit LinkedIn copy generation.")
            run_as_user = runtime.linux_user
            cwd = runtime.home_dir
        else:
            logger.warning(
                "[linkedin-copy] no TenantClaudeRuntime for tenant=%s; using server Claude login",
                tenant_id,
            )

        result = generate_linkedin_copy(
            action_run_id=action_run_id,
            title=str(synopsis_payload.get("title") or ""),
            excerpt=str(synopsis_payload.get("excerpt") or ""),
            body_preview=str(synopsis_payload.get("body_preview") or ""),
            cwd=cwd,
            run_as_user=run_as_user,
        )
        result.update(
            {
                "status": "ok",
                "tool": "switchboard.synopsis_linkedin",
                "tenant_id": str(tenant_id),
                "tenant_namespace": tenant_namespace,
                "principal_user_id": principal_user_id,
                "request_payload": request_payload,
            }
        )

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = result
        action_run.error_payload = None
        action_run.completed_at = timezone.now()
        action_run.save(
            update_fields=[
                "status",
                "result_payload",
                "error_payload",
                "completed_at",
                "updated_at",
            ]
        )
        logger.info("[linkedin-copy] ActionRun %s completed through Claude Code", action_run_id)
        return {"status": "ok", "action_run_id": action_run_id}
    except Exception as exc:
        logger.exception("[linkedin-copy] ActionRun %s failed", action_run_id)
        action_run.status = ActionRunStatus.FAILED
        action_run.result_payload = None
        action_run.error_payload = {
            "error": exc.__class__.__name__,
            "message": str(exc),
            "backend": "anthropic-claude-code",
        }
        action_run.completed_at = timezone.now()
        action_run.save(
            update_fields=[
                "status",
                "result_payload",
                "error_payload",
                "completed_at",
                "updated_at",
            ]
        )
        raise
