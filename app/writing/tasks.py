# writing/tasks.py

import json
import logging
import hashlib
import os
from django.db import transaction
from django.utils import timezone
from celery import shared_task

from concord.services.whisper import transcribe_audio
from stackroom.integration.service import ingest_object_safely
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


@shared_task(bind=True, max_retries=3, default_retry_delay=10, queue="transcription")
def transcribe_seed_task(self, seed_id: str):
    """
    Background transcription for voice seeds.
    """
    try:
        seed = Seed.objects.get(id=seed_id)
    except Seed.DoesNotExist:
        logger.error("[seeds] Seed %s not found", seed_id)
        return {"status": "missing"}

    if seed.kind != "voice":
        return {"status": "skipped", "reason": "not_voice"}

    if not seed.audio_file or not seed.audio_file.file_path:
        seed.status = "failed"
        seed.transcript_error = "Missing audio file."
        seed.save(update_fields=["status", "transcript_error", "updated_at"])
        transaction.on_commit(
            lambda: ingest_object_safely(seed, reason="seed_transcription_failed")
        )
        return {"status": "failed", "reason": "missing_audio"}

    try:
        seed.status = "processing"
        seed.save(update_fields=["status", "updated_at"])
        transaction.on_commit(
            lambda: ingest_object_safely(seed, reason="seed_transcription_processing")
        )

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
        transaction.on_commit(
            lambda: ingest_object_safely(seed, reason="seed_transcription_complete")
        )
        return {"status": "ok", "chars": len(transcript)}
    except Exception as exc:
        logger.error("[seeds] Transcription failed for %s: %s", seed_id, exc, exc_info=True)
        seed.status = "failed"
        seed.transcript_error = str(exc)
        seed.save(update_fields=["status", "transcript_error", "updated_at"])
        transaction.on_commit(
            lambda: ingest_object_safely(seed, reason="seed_transcription_failed")
        )
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
