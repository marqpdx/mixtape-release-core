import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="profiles.tasks.transcribe_intro_voice_task",
    max_retries=3,
    default_retry_delay=30,
)
def transcribe_intro_voice_task(self, profile_id):
    from profiles.models import UserProfile

    try:
        profile = UserProfile.objects.get(id=profile_id)
    except UserProfile.DoesNotExist:
        logger.warning(f"UserProfile {profile_id} not found — skipping voice transcription")
        return

    if not profile.intro_voice:
        logger.warning(f"UserProfile {profile_id} has no intro_voice — skipping")
        return

    try:
        from concord.services.whisper import transcribe_audio
        result = transcribe_audio(audio_path=profile.intro_voice, model_name="base")
        profile.intro_voice_transcript = result.text
        profile.save(update_fields=["intro_voice_transcript", "updated_at"])
        logger.info(f"[intro_voice] Transcribed {len(result.text)} chars for profile {profile_id}")
        return {"status": "success", "text_length": len(result.text)}
    except Exception as exc:
        logger.exception(f"[intro_voice] Transcription failed for profile {profile_id}: {exc}")
        raise self.retry(exc=exc)
